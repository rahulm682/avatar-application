// Everything the frontend knows about the backend API.
//
// Sessions: the access token lives ONLY in this module's memory. The refresh token is an httpOnly cookie that
// scripts cannot read; the browser attaches it when we call /auth/refresh/ with credentials: "include".

const API_URL = (
  (import.meta.env.VITE_API_URL as string | undefined) ??
  "http://localhost:8000"
).replace(/\/$/, "");

export const AVATAR_BASE_URL = (
  (import.meta.env.VITE_AVATAR_BASE_URL as string | undefined) ??
  "http://localhost:8080"
).replace(/\/$/, "");

// ---------- types ----------
export interface Profile {
  id: string;
  email: string;
  email_hash: string;
  display_name: string;
  bio: string;
  email_verified_at: string | null;
  created_at: string;
  avatar_url: string;
}

export interface Picture {
  id: string;
  width: number;
  height: number;
  size_bytes: number;
  created_at: string;
  is_current: boolean;
  preview_url: string;
}

export interface PictureList {
  results: Picture[];
  current_avatar_id: string | null;
  max_avatars: number;
}

export interface UploadTicket {
  url: string;
  fields: Record<string, string>;
  upload_token: string;
  expires_in: number;
  max_bytes: number;
}

interface Detail {
  detail: string;
}

// ---------- errors ----------
export class ApiError extends Error {
  readonly status: number;
  readonly data: unknown;

  constructor(status: number, data: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }

  /** Per-field messages from the API, e.g. { password: ["This password is too short."] }. */
  fieldErrors(): Record<string, string[]> {
    const result: Record<string, string[]> = {};
    if (this.data && typeof this.data === "object") {
      for (const [key, value] of Object.entries(
        this.data as Record<string, unknown>,
      )) {
        if (key !== "detail" && Array.isArray(value)) {
          result[key] = value.map(String);
        }
      }
    }
    return result;
  }
}

function describe(data: unknown, status: number): string {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    for (const value of Object.values(record)) {
      if (Array.isArray(value) && value.length > 0) return String(value[0]);
    }
  }
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  if (status >= 500) return "The server had a problem. Try again in a moment.";
  return "Something went wrong. Try again.";
}

// ---------- session state ----------
let accessToken: string | null = null;
let refreshPromise: Promise<boolean> | null = null;
let sessionExpiredHandler: (() => void) | null = null;

export function clearAccessToken(): void {
  accessToken = null;
}

/** Called when the session is gone for good (the refresh cookie is missing, expired or revoked). */
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  sessionExpiredHandler = handler;
}

/**
 * Gets a new access token using the refresh cookie. Refresh tokens work exactly once, so two parallel calls
 * would log the user out: every caller shares one request while it is in flight ("single flight").
 */
export function refreshSession(): Promise<boolean> {
  if (refreshPromise === null) {
    refreshPromise = (async () => {
      try {
        const response = await fetch(`${API_URL}/api/auth/refresh/`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" }, // required by the server's CSRF check
          body: "{}",
        });
        if (!response.ok) {
          accessToken = null;
          return false;
        }
        accessToken = ((await response.json()) as { access: string }).access;
        return true;
      } catch {
        return false;
      }
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

// ---------- requests ----------
async function send(
  method: string,
  path: string,
  body: unknown,
  withToken: boolean,
): Promise<Response> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (withToken && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  try {
    return await fetch(`${API_URL}${path}`, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      0,
      null,
      "Cannot reach the server. Check that the backend is running.",
    );
  }
}

async function requestFull<T>(
  method: string,
  path: string,
  body?: unknown,
  authenticated = true,
): Promise<{ status: number; data: T }> {
  let response = await send(method, path, body, authenticated);

  if (response.status === 401 && authenticated) {
    // The access token expired (they last 15 minutes): get a new one and try again, once.
    if (await refreshSession()) {
      response = await send(method, path, body, authenticated);
    }
    if (response.status === 401) {
      sessionExpiredHandler?.();
    }
  }

  const text = response.status === 204 ? "" : await response.text();
  let data: unknown;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = undefined; // not JSON (an HTML error page, for instance): the status code still tells the story
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, data, describe(data, response.status));
  }
  return { status: response.status, data: data as T };
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  authenticated = true,
): Promise<T> {
  return (await requestFull<T>(method, path, body, authenticated)).data;
}

// ---------- direct upload to S3 ----------
export function uploadToStorage(
  ticket: UploadTicket,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [name, value] of Object.entries(ticket.fields))
      form.append(name, value);
    form.append("file", file); // S3 requires the file to be the LAST field

    const xhr = new XMLHttpRequest();
    xhr.open("POST", ticket.url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(
          new ApiError(
            xhr.status,
            null,
            "The storage server rejected the file. Check its type and size.",
          ),
        );
      }
    };
    xhr.onerror = () =>
      reject(
        new ApiError(
          0,
          null,
          "The upload could not reach the storage server. Check that it is running and that its CORS rule allows this site.",
        ),
      );
    xhr.send(form);
  });
}

// ---------- the API ----------
export const api = {
  // sign-up and verification
  register: (email: string, password: string) =>
    request<Detail>("POST", "/api/auth/register/", { email, password }, false),
  resendVerification: (email: string) =>
    request<Detail>("POST", "/api/auth/resend-verification/", { email }, false),
  verifyEmail: (token: string) =>
    request<Detail>("POST", "/api/auth/verify-email/", { token }, false),

  // session
  async login(email: string, password: string): Promise<Profile> {
    const result = await request<{ access: string; user: Profile }>(
      "POST",
      "/api/auth/login/",
      { email, password },
      false,
    );
    accessToken = result.access;
    return result.user;
  },
  async logout(): Promise<void> {
    try {
      await request<void>("POST", "/api/auth/logout/", {}, false);
    } finally {
      accessToken = null;
    }
  },

  // passwords
  requestPasswordReset: (email: string) =>
    request<Detail>(
      "POST",
      "/api/auth/password-reset/request/",
      { email },
      false,
    ),
  confirmPasswordReset: (uid: string, token: string, newPassword: string) =>
    request<Detail>(
      "POST",
      "/api/auth/password-reset/confirm/",
      { uid, token, new_password: newPassword },
      false,
    ),
  async changePassword(
    currentPassword: string,
    newPassword: string,
  ): Promise<void> {
    const result = await request<{ access: string }>(
      "POST",
      "/api/auth/change-password/",
      {
        current_password: currentPassword,
        new_password: newPassword,
      },
    );
    accessToken = result.access; // the server started a fresh session for this device
  },

  // email change
  requestEmailChange: (newEmail: string, password: string) =>
    request<Detail>("POST", "/api/auth/email-change/request/", {
      new_email: newEmail,
      password,
    }),
  confirmEmailChange: (token: string) =>
    request<Detail>(
      "POST",
      "/api/auth/email-change/confirm/",
      { token },
      false,
    ),

  // profile
  getMe: () => request<Profile>("GET", "/api/me/"),
  updateMe: (changes: { display_name: string; bio: string }) =>
    request<Profile>("PATCH", "/api/me/", changes),
  deleteAccount: (password: string) =>
    request<void>("DELETE", "/api/me/", { password }),

  // pictures
  listPictures: () => request<PictureList>("GET", "/api/avatars/"),
  getUploadTicket: (contentType: string, size: number) =>
    request<UploadTicket>("POST", "/api/avatars/upload-url/", {
      content_type: contentType,
      size,
    }),
  async confirmUpload(
    uploadToken: string,
  ): Promise<{ picture: Picture; created: boolean }> {
    const { status, data } = await requestFull<Picture>(
      "POST",
      "/api/avatars/confirm/",
      { upload_token: uploadToken },
    );
    return { picture: data, created: status === 201 };
  },
  setCurrentPicture: (id: string | null) =>
    request<{ current_avatar_id: string | null }>(
      "PUT",
      "/api/me/current-avatar/",
      { avatar_id: id },
    ),
  deletePicture: (id: string) => request<void>("DELETE", `/api/avatars/${id}/`),
};

// ---------- helpers ----------
/** The public address of a picture, as other applications use it. */
export function avatarUrl(
  emailHash: string,
  size: number,
  cacheBuster?: number,
): string {
  const base = `${AVATAR_BASE_URL}/avatar/${emailHash}?s=${size}`;
  // The CDN ignores unknown parameters, but the browser treats a new value as a new URL: handy right after a change.
  return cacheBuster === undefined ? base : `${base}&v=${cacheBuster}`;
}
