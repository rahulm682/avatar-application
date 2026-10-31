# Avatar Service: Design Document

**Version:** 0.4 (draft for implementation; local Docker development first with Silo as local S3 and Varnish as local CDN)
**Date:** 3 October 2026
**Purpose:** A Gravatar-like service where each user has one verified email, uploads multiple profile pictures, and selects one as the current picture. Other applications fetch the current picture by the SHA-256 hash of the user's email.

> **Nature of the project:** This is a **learning project**, not a production system. The main goals are to practice **CDNs, caching and AWS S3** hands-on. Hosting is a secondary task, so every choice favors the free tier and simplicity. Things that would be required for production (custom domain, end-to-end HTTPS, automated moderation, and so on) are listed under *Future Considerations*.

---

## 1. Goals and Non-Goals

### Goals
- Users register with one email and password, verify the email, and manage a profile (display name, bio).
- A user can upload multiple pictures and choose one as the **current avatar**.
- Any third-party application can fetch the current avatar with a plain `<img>` tag, using only the SHA-256 hash of the user's email.
- Serve images fast through a **CDN**, with **cache invalidation** when the current avatar changes.
- Practice S3 features (first on a local Silo server, then on AWS S3): private buckets, IAM roles, presigned uploads, bucket CORS, lifecycle rules, and a derived-image cache.
- Stay within free tiers (AWS, Supabase, CloudFront).

### Non-Goals (for now)
- Production-grade availability, custom domain, or full HTTPS between every hop.
- Multiple emails per user, social login, API keys for third-party apps.
- Automated content moderation.
- Arbitrary image sizes.

---

## 2. Key Decisions Summary

| Area | Decision |
|---|---|
| Lookup identifier | SHA-256 of the normalized email (trim, lowercase). Email hash is the **only** lookup method. |
| Emails per user | **One** email per user |
| Email verification | Required. **Unverified accounts cannot log in.** |
| Login errors | Single generic message: "email or password is wrong" |
| Image storage | S3 API with private buckets. **Local development: Silo** (S3-compatible server in Docker). Hosted: AWS S3, with separate dev and prod buckets |
| CDN | **Local development: Varnish container** in front of the public avatar endpoint. Hosted: Amazon CloudFront (free tier) |
| Cache freshness | `Cache-Control` TTLs plus **CDN invalidation** when the current avatar changes (Varnish ban locally, CloudFront invalidation when hosted) |
| Image sizes | **Fixed set of sizes** (arbitrary sizes are a future item) |
| Derived-image cache | Resized images cached in S3 under `derived/` (in MVP, as a learning goal) |
| Uploads | **Presigned direct-to-S3 uploads** with server-side validation on confirm (in MVP, as a learning goal) |
| Tokens (email verification, reset, email change) | Stateless **signed tokens** (no token table) |
| Backend | Python, Django, Django REST Framework |
| Database | PostgreSQL (container in Docker Compose now; Supabase is a candidate for hosting later) |
| Frontend | React (Vite, TypeScript) |
| Development approach | **Everything runs locally in Docker Compose first.** Hosting, CDN and deployment are decided after all features work locally |
| Hosting | Decided later. When hosted, the frontend and backend are hosted separately |
| Cross-origin handling | **CORS with credentials** configured on the Django server |
| Session tokens | Short-lived access token in memory (sent as `Authorization: Bearer`); **refresh token in an httpOnly, Secure, `SameSite=None` cookie** (never readable by page scripts) |
| Moderation | Manual only (report endpoint plus Django admin) |

---

## 3. High-Level Architecture

```
                        +-------------------------+
                        |  Third-party apps       |
                        |  <img src=".../avatar/  |
                        |   {email_hash}?s=160">  |
                        +-----------+-------------+
                                    |
   +--------------------+           v
   | React frontend     |   +---------------+   cache miss   +--------------------+
   | (static hosting)   |   |  CloudFront   +--------------->|  Django on EC2     |
   +---------+----------+   |  (CDN, cache) |<---------------+  (Docker + Nginx)  |
             |              +---------------+   image bytes  +----+----------+----+
             | JSON API (CORS + credentials)                       |          |
             +---------------------------------------------------->|          |
                                                                   |          |
                                          +------------------------+          +-----------+
                                          v                                               v
                                 +-----------------+                          +--------------------+
                                 | S3 bucket       |                          | Supabase Postgres  |
                                 | uploads/        |                          | users, avatars,    |
                                 | originals/      |                          | reports, tokens    |
                                 | derived/        |                          +--------------------+
                                 +-----------------+
                                          ^
   Browser uploads directly (presigned POST) -+
```

*The diagram shows the hosted layout. In local development, CloudFront is replaced by a Varnish container, S3 by a Silo container, Supabase by a Postgres container, and EC2 by Docker Compose on your machine (see section 13).*

### Two backend surfaces
1. **Management API** (`/api/...`): JSON, authenticated, called by the React app directly (cross-origin, CORS enabled). Not cached.
2. **Public avatar endpoint** (`/avatar/{email_hash}`): no authentication, returns image bytes, always accessed through the CDN (Varnish locally, CloudFront when hosted).

---

## 4. Data Model

### 4.1 `users` (custom Django user model, email as login field)

| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| email | varchar, unique | Stored normalized (trimmed, lowercased) |
| email_hash | char(64), unique, indexed | SHA-256 hex of the normalized email |
| password | varchar | Argon2id hash |
| email_verified_at | timestamptz, nullable | Null means unverified (cannot log in) |
| display_name | varchar(80) | |
| bio | text (max 500) | |
| current_avatar_id | UUID, FK to avatars, nullable, ON DELETE SET NULL | The selected avatar |
| is_active / is_staff | boolean | Staff can use Django admin for moderation |
| created_at / updated_at | timestamptz | |

### 4.2 `avatars`

| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| user_id | UUID, FK to users, ON DELETE CASCADE | |
| storage_key | varchar | e.g. `originals/{user_id}/{avatar_id}.webp` |
| content_hash | char(64) | SHA-256 of the processed image bytes (can detect duplicates) |
| mime_type | varchar | `image/webp` after processing |
| size_bytes | integer | |
| width / height | integer | |
| created_at | timestamptz | |

Limit: **10 avatars per user**.

### 4.3 `reports`

| Column | Type | Notes |
|---|---|---|
| id | UUID, PK | |
| avatar_id | UUID, FK, nullable | The reported image, if it still exists |
| email_hash | char(64) | The hash that was reported |
| reason | varchar(500) | |
| status | enum | `open`, `actioned`, `dismissed` |
| created_at | timestamptz | |

### 4.4 Refresh tokens
Handled by the `djangorestframework-simplejwt` token blacklist tables (outstanding and blacklisted tokens), so no custom table is needed. This is the one place where server-side token state is kept, so logout and password changes can revoke sessions.

### 4.5 No token table for email flows
Verification, password-reset and email-change links use **stateless signed tokens** (see section 6).

---

## 5. Email Hash and Lookup

- **Normalization:** `email.strip().lower()`, then `sha256(...)` as lowercase hex (64 characters). Every consumer must apply the same rule, so we document it publicly with code examples (JavaScript, Python).
- `email_hash` is computed when the user is created and recomputed when the email changes.
- **Known limitation (documented, accepted):** the hash hides the email from casual viewers but not from targeted guessing. Anyone who guesses an email can hash it and check whether an avatar exists.
- **Known limitation (accepted):** changing the email changes the hash, so URLs already embedded in other applications stop resolving to the user's avatar.

---

## 6. Authentication and Account Flows

### 6.1 Overview
- **Credentials:** email and password.
- **Password hashing:** Argon2id (`argon2-cffi`), with Django's password validators (minimum length, common-password check).
- **Access token:** short-lived (15 minutes), returned in the JSON body of login and refresh, kept **in memory only** by the React app (never in localStorage or sessionStorage), and sent as `Authorization: Bearer <token>`.
- **Refresh token:** longer-lived (about 7 days), delivered **only as a cookie** and never in a response body, so page scripts cannot read it. It is rotated on every use and blacklisted on logout or password change.
- **Cookie attributes:** `HttpOnly; Secure; SameSite=None; Path=/api/auth/; Max-Age=604800`. `Secure` means the API must be served over HTTPS. `Path` limits the cookie to the auth endpoints, so it is not sent with other API calls.
- **Cross-site cookie:** the frontend and backend are on different sites, so this is a third-party cookie. It works because of `SameSite=None; Secure` plus CORS with credentials (section 10). Some browsers block it (see Known Limitations).
- **Page reload:** the in-memory access token is lost, so the app calls `POST /api/auth/refresh`. The browser attaches the cookie automatically and the app receives a new access token.
- **CSRF protection:** `SameSite=None` means the browser would attach the cookie to requests from any site, so the cookie-using endpoints (`/auth/refresh`, `/auth/logout`) need their own protection:
  - The server rejects the request unless the `Origin` header matches an allowed frontend origin.
  - These endpoints accept only `Content-Type: application/json`, which cross-site forms cannot send. It also forces a CORS preflight check, which only allowed origins pass.
  - All other endpoints use the Bearer header, which the browser never attaches automatically, so they are not exposed to CSRF.

### 6.2 Sign-up and verification
1. `POST /api/auth/register {email, password}` creates an unverified user and emails a verification link. The response is the same whether or not the email is already registered, so sign-up does not reveal which emails exist.
2. The link points to the React route `/verify-email?token=...`. The page calls `POST /api/auth/verify-email {token}`.
3. The token is signed with `django.core.signing` and contains user id, email, and purpose `verify_email`, with a **24 hour** expiry. Verifying twice is harmless (no-op).
4. **Stale unverified accounts:** an unverified record is deleted after about 24 hours (scheduled cleanup command). A new sign-up with an email held by an unverified record replaces that record, so a real owner is never blocked by someone who signed up with their email.
5. `POST /api/auth/resend-verification {email}`: rate-limited, with the same response whether or not the email exists.

### 6.3 Login
- `POST /api/auth/login {email, password}`. The response body contains the access token only. The refresh token is set as the httpOnly cookie described in 6.1.
- Unknown email, wrong password, **and unverified account** all return the same generic error: "email or password is wrong". The login page links to "resend verification email".
- To avoid timing leaks, a dummy password hash check runs when the email is unknown.

### 6.4 Password reset
- `POST /api/auth/password-reset/request {email}` always responds the same way.
- Token uses Django's `PasswordResetTokenGenerator`, which includes a fingerprint of the current password hash, so it becomes invalid after the password changes (effectively single-use) and expires in **1 hour**.
- Password reset and password change blacklist all of the user's refresh tokens.

### 6.5 Email change
- `POST /api/auth/email-change/request {new_email, password}` sends a link to the **new** address.
- The signed token carries user id, new email, purpose `change_email`, and expires in 24 hours.
- On confirm, `email` and `email_hash` are updated, and the CDN is invalidated for **both** the old and new hash paths.
- If the new email already belongs to another account, the confirm step fails with a generic message.

### 6.6 Email delivery
- **Local:** a Mailpit container catches all emails, and the verification and reset links can be opened in its web UI (port 8025).
- **Optional later:** Amazon SES (sandbox mode requires verified recipient addresses).

### 6.7 Signing secret
The signing secret comes from an environment variable. If it leaks, tokens could be forged, so the settings support key rotation (`SECRET_KEY_FALLBACKS`).

---

## 7. Management API

All routes are under `/api`. JSON in and out. Authenticated unless marked public.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Sign up (public) |
| POST | `/auth/verify-email` | Confirm email token (public) |
| POST | `/auth/resend-verification` | Resend link (public, rate-limited) |
| POST | `/auth/login` | Returns the access token in the body and sets the refresh-token cookie (public) |
| POST | `/auth/refresh` | Reads the refresh cookie, rotates it (sets a new cookie), returns a new access token. Origin check applies |
| POST | `/auth/logout` | Blacklists the refresh token and clears the cookie. Origin check applies |
| POST | `/auth/password-reset/request` | Request reset link (public) |
| POST | `/auth/password-reset/confirm` | Set new password with token (public) |
| POST | `/auth/change-password` | Change password (logged in) |
| POST | `/auth/email-change/request` | Start email change |
| POST | `/auth/email-change/confirm` | Confirm email change |
| GET / PATCH | `/me` | Read or update profile (display name, bio) |
| DELETE | `/me` | Delete account and all avatars |
| POST | `/avatars/upload-url` | Get a presigned S3 POST (see section 8) |
| POST | `/avatars/confirm` | Validate and register an uploaded image |
| GET | `/avatars` | List the user's avatars (with preview URLs) |
| DELETE | `/avatars/{id}` | Delete an avatar |
| PUT | `/me/current-avatar` | Set the current avatar `{avatar_id}` (or null) |
| POST | `/reports` | Report an avatar (public, rate-limited) |

An **OpenAPI** schema is generated with `drf-spectacular`, so frontend and backend share one contract.

---

## 8. Image Upload and Processing Pipeline

### 8.1 S3 layout (per bucket)

```
uploads/{user_id}/{upload_id}              raw browser uploads (temporary, expire in 1 day)
originals/{user_id}/{avatar_id}.webp       validated, re-encoded full-size image
derived/{avatar_id}/{size}.webp            cached resized square images
```

### 8.2 Upload flow (presigned POST)
1. The React app calls `POST /api/avatars/upload-url {content_type, size}`. Django checks the avatar count (max 10) and returns a **presigned POST** with conditions: `content-length-range` up to **5 MB**, content type limited to JPEG, PNG or WebP, and a fixed key under `uploads/{user_id}/{upload_id}`. It also returns a signed `upload_token` (user id, key, expiry), so no database table is needed.
2. The browser uploads the file directly to S3 (the bucket needs a **CORS rule** for this).
3. The browser calls `POST /api/avatars/confirm {upload_token}`.
4. Django downloads the object and:
   - checks the real format **by content**, not the file extension or the browser's claim;
   - enforces a maximum pixel size (e.g. 4096 x 4096) to prevent decompression-bomb attacks;
   - **re-encodes** the image, which strips EXIF data (such as GPS location) and neutralizes malformed files;
   - writes the result to `originals/` as a high-quality WebP;
   - creates the `avatars` row and deletes the raw upload.
5. A **lifecycle rule** expires abandoned `uploads/` objects after 1 day.

Presigned POST is used instead of presigned PUT because POST policies can enforce a maximum file size.

### 8.3 Fixed sizes
Supported square sizes (proposed): **40, 80, 160, 320, 640** pixels. The `s` parameter is rounded up to the nearest supported size, capped at 640, and defaults to **80**. Arbitrary sizes (`s=1..2048`) are listed under Future Considerations.

### 8.4 Resizing
Resizing happens on demand (CDN miss and no `derived/` object): center-crop to a square, resize with a high-quality filter, encode as WebP (quality about 80). Two simultaneous misses may both compute the result. This is harmless because the output is identical and the last write wins.

---

## 9. Public Avatar Endpoint and Caching

### 9.1 Endpoint
```
GET /avatar/{email_hash}?s=160&d=identicon
```

| Parameter | Values | Default |
|---|---|---|
| `email_hash` | 64-character lowercase hex SHA-256 | required |
| `s` | one of the fixed sizes (rounded up) | 80 |
| `d` | `default` (generic image), `identicon` (generated from the hash), `404` | `default` |

### 9.2 Lookup algorithm (on CDN miss)
1. Validate the hash format.
2. Snap the size to a supported size.
3. Find the user by `email_hash`, then `current_avatar_id`.
4. If an avatar exists: check S3 `derived/{avatar_id}/{size}.webp`. On hit, return it. On miss, read the original, resize, save to `derived/`, return it.
5. If there is no user or no avatar: respond according to `d` (404, the default image, or a deterministic identicon).

### 9.3 Cache layers
| Layer | What it caches | Lifetime |
|---|---|---|
| Browser / other apps | Final image | `max-age=300` (5 minutes) |
| CDN edge (Varnish locally, CloudFront when hosted) | Final image | `s-maxage=86400` (1 day), cleared by invalidation |
| S3 `derived/` | Resized images, keyed by avatar id | Until the avatar is deleted |

Response headers: `Cache-Control: public, max-age=300, s-maxage=86400`, plus an `ETag`. A 404 response uses a short TTL.

**CDN cache key:** path plus only the `s` and `d` query parameters (everything else ignored), so random query strings cannot fill the cache.

### 9.4 Invalidation
Whenever what the public URL should return changes, the server asks the CDN to invalidate `/avatar/{email_hash}*` (a Varnish ban locally, the CloudFront invalidation API when hosted). One wildcard path clears all size and fallback variants and counts as a single invalidation path.

Triggers:
- The user sets or changes the current avatar.
- The user uploads a first avatar (previously cached responses were fallback images).
- The user deletes the current avatar.
- Email change (invalidate both old and new hashes).
- Account deletion or a moderator removing an avatar.

Notes:
- Invalidation is eventually consistent and can take a minute or two.
- It does not clear browser caches, which is why `max-age` stays short.
- If the API call fails, it is retried in the background. The TTLs act as a safety net.
- Free monthly invalidation paths are limited (verify the current number before relying on it).

### 9.5 Origin protection
The CDN (Varnish locally, CloudFront when hosted) adds a secret custom header (e.g. `X-Origin-Verify`) when calling the origin. Nginx or Django rejects `/avatar/*` requests without it, so nobody can bypass the CDN. The `/api` routes are called directly by the React app, so they are protected by authentication and rate limits instead.

---

## 10. Cross-Origin (CORS) Setup

The frontend and backend are on different domains, so the browser enforces CORS.

**Django (`django-cors-headers`):**
- `CORS_ALLOWED_ORIGINS`: exact frontend URLs from environment variables (dev and prod). **No wildcard**, because browsers refuse a wildcard when credentials are enabled.
- `CORS_ALLOW_CREDENTIALS = True`, so the browser accepts and sends the refresh cookie on cross-origin calls.
- Allowed headers include `Authorization` and `Content-Type`.
- A reasonable preflight cache (`CORS_PREFLIGHT_MAX_AGE`) reduces extra requests.
- The React app must send every API request with `credentials: "include"` (or `withCredentials: true` in axios), otherwise the cookie is neither stored nor sent.
- Django's `CSRF_TRUSTED_ORIGINS` and the Origin check from section 6.1 use the same allowed-origins setting.

**S3 bucket CORS:** allows the frontend origins to `POST` (direct upload) and exposes the `ETag` header. Silo supports a per-bucket CORS configuration that overrides the server-wide setting, so the rule is configured the same way as on AWS.

**Public avatar endpoint:** `<img>` tags need no CORS. If someone loads avatars through `fetch` or a canvas, `Access-Control-Allow-Origin: *` can be added to the avatar responses (optional).

**HTTPS is mandatory for the hosted API** (not needed for local development). The refresh cookie is `Secure`, so browsers only store and send it over HTTPS. Also, an HTTPS frontend cannot call a plain HTTP backend ("mixed content"). One free approach without a domain is a second CloudFront distribution in front of the API with caching disabled, which provides an `https://...cloudfront.net` address and forwards to EC2 over HTTP. Choose the approach when deploying.

**Local development:** browsers treat `localhost` as a secure context and consider different ports on `localhost` the same site, so the cookie flow works in dev even without HTTPS. The cross-site behavior only shows up once the apps are deployed to different domains, so test the deployed setup early.

---

## 11. Security and Abuse Controls

| Area | Control |
|---|---|
| Passwords | Argon2id, password validators, rate-limited login |
| Account enumeration | Generic responses on login, sign-up, resend and reset; constant-time-ish login |
| Uploads | 5 MB limit, 10 avatars per user, content-based type check, pixel limit, re-encode (EXIF stripped) |
| S3 | Private buckets, no public access, IAM role on EC2 (no stored keys), separate dev and prod buckets and credentials |
| Origin | Secret header lock for the CDN-fronted avatar endpoint |
| Rate limits (proposed) | Login 5/min per IP and email; register 5/hour per IP; resend 3/hour; upload-url 20/hour per user; reports 10/hour per IP (`django-ratelimit`) |
| Moderation | **Manual:** `POST /api/reports` plus Django admin. An admin can delete an avatar, deactivate a user, and the system invalidates the CDN |
| Secrets | Environment variables; signing secret rotation supported |
| Session tokens | Access token in memory only; refresh token in an httpOnly cookie that scripts cannot read, so XSS cannot steal it directly; rotation with server-side blacklist |
| CSRF | Origin allowlist and JSON-only content type on `/auth/refresh` and `/auth/logout`; all other endpoints use the Bearer header |
| Transport | HTTPS between browsers and the CDN or API (mandatory for the API because of the `Secure` cookie, see section 10) |

---

## 12. Technology Stack

### Backend
- Python, Django, Django REST Framework
- `djangorestframework-simplejwt` (access and refresh tokens, blacklist). Its stock views return the refresh token in the body, so we write thin custom login, refresh and logout views that set and read the httpOnly cookie
- `django-cors-headers`, `django-ratelimit`
- `drf-spectacular` (OpenAPI)
- `boto3` and `django-storages` (S3 API: works against Silo locally and AWS S3 when hosted)
- Pillow (image processing)
- `argon2-cffi` (password hashing)
- Gunicorn (about 2 workers on a small instance), Nginx as reverse proxy

### Database: PostgreSQL (local container now, Supabase candidate later)
- **Now:** a Postgres container in Docker Compose. **Later:** a hosted database (for example Supabase) by changing `DATABASE_URL` only.
- Used purely as managed Postgres. Django handles auth, and S3 handles images.
- Free plan: 500 MB per project, two free projects (one for dev, one for prod). **Projects pause after one week of inactivity** and must be restored from the dashboard.
- Create the project in the same region as the EC2 instance.
- Connect through Supabase's **connection pooler** (the direct connection may require IPv6). Behind a transaction pooler, set Django's `DISABLE_SERVER_SIDE_CURSORS = True`.

### Frontend
- Vite, React, TypeScript, React Router, TanStack Query.
- Types generated from the OpenAPI schema.
- Access token kept in memory only. The refresh token lives in the httpOnly cookie, which the app never touches. All API calls use `credentials: "include"`, and on app start the app calls `/auth/refresh` to restore the session.
- Routes: `/register`, `/check-email`, `/verify-email`, `/login`, `/forgot-password`, `/reset-password`, `/confirm-email-change`, `/profile`, `/avatars`.

---

## 13. Local Development with Docker (Current Focus) and Hosting (Later)

### 13.1 Approach
- **First goal:** build the whole application with every feature working **locally**, running in **Docker containers**.
- **Local stand-ins for the cloud parts:** **Silo** plays the role of S3, and a **Varnish** container plays the role of the CDN. This makes the local setup look like production, so it teaches the same concepts without needing an AWS account.
- **Hosting is deferred.** Which hosts to use for the frontend, backend, database and CDN is decided after the local version works.
- Everything is configured through environment variables and containers, so moving to AWS later should need configuration changes, not code changes.

### 13.2 Docker Compose services

| Service | Image / build | Purpose | Port |
|---|---|---|---|
| `db` | `postgres:16` with a named volume | PostgreSQL database | 5432 |
| `silo` | `pgsty/silo` (pin a release tag), run as `server /data --console-address ":9001"` with a named volume | Local **S3-compatible object storage** (a community-maintained fork of MinIO). Includes a web console for browsing buckets and objects | 9000 (S3 API), 9001 (console) |
| `silo-init` | One-shot job (a Python script using `boto3`) | Creates the dev bucket, applies the bucket CORS rule and the `uploads/` lifecycle rule, and checks that the setup works. Using `boto3` means the same script can later run against real AWS S3 | none |
| `varnish` | Official `varnish` image with a mounted `cdn/default.vcl` | Local **CDN**: a caching reverse proxy in front of `/avatar/*` | 8080 |
| `backend` | Built from `backend/Dockerfile` | Django API and public avatar endpoint (origin for Varnish). In dev it runs the Django dev server with the source mounted for hot reload. A production-like variant runs Gunicorn | 8000 |
| `frontend` | Node image running the Vite dev server, source mounted | React app with hot reload | 5173 |
| `mailpit` | `axllent/mailpit` | Catches all outgoing email. Verification and reset links can be opened in its web UI | 8025 (UI), 1025 (SMTP) |

Useful commands to support from day one: `docker compose up --build`, migrations and a superuser via `docker compose exec backend ...`, and a `make` or script wrapper for the common tasks.

### 13.3 Request paths locally

```
Third-party app / browser <img>  --->  Varnish :8080  --- miss --->  Django :8000  --->  Silo :9000
React app (JSON API)             ------------------------------->  Django :8000
Browser upload (presigned POST)  ------------------------------->  Silo :9000  (direct)
```

As in the planned production setup, only avatar images go through the CDN. The React app calls the API directly, and uploads go straight from the browser to storage.

### 13.4 What is real and what is simulated locally

| Feature | Local approach |
|---|---|
| S3 images | **Silo**, an S3-compatible server. It speaks the S3 API (presigned POST, bucket CORS, lifecycle rules, bucket policies), but it is **not an AWS emulator**: there is no AWS IAM, STS, or role system. It has its own users, access keys and policies in a similar JSON format |
| CDN | **Varnish.** It behaves like a real shared cache (see 13.5), but it has no edge locations and is not CloudFront, so cache-key and invalidation details differ and must be re-checked later |
| Database | Postgres container. Supabase (or another host) can replace it later by changing `DATABASE_URL` only |
| Email | Mailpit container |
| Origin secret header | Enabled locally: Varnish adds it to every request it sends to Django, and Django rejects `/avatar/*` requests without it |
| HTTPS and cookies | Plain HTTP on `localhost`. The refresh cookie uses relaxed settings locally (`Secure=False`, `SameSite=Lax`), since different ports on `localhost` count as the same site. The real `SameSite=None; Secure` setup is tested after deployment |

Never commit credentials. Provide a `.env.example` with placeholder values. The Django app uses its own Silo access key restricted to the dev bucket, never the Silo root user.

### 13.5 Local CDN with Varnish

`cdn/default.vcl` is a small configuration file (about 30 to 50 lines) that does the following:

- Sends cache misses to the `backend` service, and adds the `X-Origin-Verify` secret header.
- Caches only `GET /avatar/*`. Everything else passes through uncached.
- Builds the cache key from the path plus only the `s` and `d` query parameters (other parameters are dropped), matching section 9.3.
- Uses the response's `s-maxage` as the CDN lifetime, while browsers follow `max-age`.
- Adds `X-Cache: HIT` or `MISS` to responses. Varnish adds `Age` automatically.
- Accepts a `BAN` request, **only from the backend container**, that removes cached entries whose URL matches a pattern such as `^/avatar/{email_hash}`. This is the local equivalent of the CloudFront wildcard invalidation. The backend's invalidation service sends it when `INVALIDATION_BACKEND=varnish`.

Optional learning extras: serving stale content while revalidating (grace mode), and watching hit ratio with `varnishstat`.

If Varnish proves too heavy for your needs, an Nginx container with `proxy_cache` is the simpler fallback. Its open-source version has no pattern-based purge, though, so invalidation practice would be limited.

### 13.6 Silo-specific notes

- **Two endpoints.** The backend container talks to Silo at `http://silo:9000` (Docker network), but a presigned URL contains the host the browser must reach, `http://localhost:9000`. Presigned POSTs are signed with a client configured with the public endpoint (signing needs no network call), while server-side reads and writes use the internal endpoint. See `AWS_S3_ENDPOINT_URL` and `AWS_S3_PUBLIC_ENDPOINT_URL`.
- **Path-style addressing.** Use `bucket` in the URL path (`localhost:9000/bucket/key`), not as a subdomain.
- **Pin the image tag** in `docker-compose.yml`, and re-run the smoke test when upgrading. Silo is a community fork of MinIO released under AGPL-3.0. We only talk to it over the network, so none of its code becomes part of this application.
- **Policies:** when writing bucket or user policies, list both `arn:aws:s3:::avatars-dev` and `arn:aws:s3:::avatars-dev/*`. Some bucket-level write actions are not granted by the `/*` resource alone, which is also the correct habit for AWS.
- **Console:** `http://localhost:9001` lets you browse objects, check the `uploads/`, `originals/` and `derived/` folders, and inspect bucket settings while developing.
- **S3 smoke test (run at setup, by `silo-init` or a test):**
  1. Create the bucket and confirm anonymous access is denied.
  2. Apply the per-bucket CORS rule, then perform a real browser-style presigned POST from `http://localhost:5173`.
  3. Confirm the POST policy rejects an oversized file and a wrong content type.
  4. Apply the lifecycle rule for `uploads/` and confirm it is stored (expiry timing can differ from AWS).
  5. Upload, read, list and delete objects with the app's restricted access key.

### 13.7 Proposed repository layout

```
avatar-service/
  docker-compose.yml
  .env.example
  cdn/
    default.vcl         Varnish configuration (local CDN)
  scripts/
    init_s3.py          bucket, CORS, lifecycle, smoke test (boto3)
  backend/
    Dockerfile
    manage.py
    config/             Django settings, urls
    apps/
      accounts/         users, auth, email flows
      avatars/          uploads, processing, public endpoint, invalidation service
      moderation/       reports
  frontend/
    Dockerfile
    src/
  docs/
    avatar-service-design.md
```

### 13.8 Moving to AWS later (reference notes, not decided)
Switching from the local stand-ins to AWS should be configuration only:

| Concern | Local | AWS |
|---|---|---|
| Object storage | Silo, `AWS_S3_ENDPOINT_URL=http://silo:9000`, path-style | Real S3 bucket, endpoint variables empty, default addressing |
| Credentials | Silo access key in `.env` | IAM role (hosted on AWS) or an IAM user key |
| CDN | Varnish, `INVALIDATION_BACKEND=varnish` | CloudFront, `INVALIDATION_BACKEND=cloudfront` |
| `AVATAR_BASE_URL` | `http://localhost:8080` | The CloudFront address |

Then re-run the smoke test against real S3 and compare behavior. Other notes from our earlier discussion:
- **AWS account:** not needed until this stage. A new account gets up to $200 in credits and chooses a Free plan (closes after 6 months or when credits run out) or a Paid plan. Launch only "Free tier eligible" instances, enable MFA on the root user, use an IAM user for daily work, and set an AWS Budgets alert.
- **Database:** Supabase's free plan gives 500 MB per project and pauses a project after a week of inactivity. Connect through its pooler and set `DISABLE_SERVER_SIDE_CURSORS = True`.
- **Backend:** the same Docker images can run on a small VM.
- **Frontend:** a static host serving the Vite build.
- Free-tier terms change often, so verify them when we get there.
---

## 14. Configuration Reference (environment variables)

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` / `SECRET_KEY_FALLBACKS` | Signing secret and rotation |
| `DATABASE_URL` | Supabase pooler connection string |
| `AWS_STORAGE_BUCKET_NAME` | `avatars-dev` (local Silo) or the hosted bucket name |
| `AWS_REGION` | S3 region (`us-east-1` works for Silo) |
| `AWS_S3_ENDPOINT_URL` | Internal S3 endpoint used by the backend container, e.g. `http://silo:9000`. Empty for real AWS |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | Endpoint the **browser** can reach, used only to sign presigned POSTs, e.g. `http://localhost:9000`. Empty for real AWS |
| `AWS_S3_ADDRESSING_STYLE` | `path` for Silo, default for AWS |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Locally: an access key created in Silo for the application (never the Silo root user), kept in a git-ignored `.env`. When hosted on AWS, prefer an IAM role |
| `CLOUDFRONT_DISTRIBUTION_ID` | Target for invalidations (not needed locally) |
| `INVALIDATION_BACKEND` | `varnish` (local ban request), `cloudfront` (hosted), or `log` (no-op) |
| `VARNISH_BAN_URL` | Internal URL of the Varnish container for ban requests, e.g. `http://varnish:80` |
| `SILO_ROOT_USER` / `SILO_ROOT_PASSWORD` | Passed to the Silo container as its root credentials (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`). Used only by setup scripts and the console |
| `AVATAR_BASE_URL` | Public base URL for avatars: the Varnish address locally (e.g. `http://localhost:8080`), the CloudFront address when hosted. Kept as config so a domain can be added later |
| `CDN_ORIGIN_SECRET` | Value of the origin-verify header |
| `CORS_ALLOWED_ORIGINS` | Exact frontend origins. Also used for the Origin check on refresh and logout and for `CSRF_TRUSTED_ORIGINS` |
| `REFRESH_COOKIE_NAME` / `REFRESH_COOKIE_PATH` | Cookie name and path (default path `/api/auth/`) |
| `REFRESH_COOKIE_SECURE` / `REFRESH_COOKIE_SAMESITE` | `True` and `None` when deployed; relaxed values are fine in local dev |
| `FRONTEND_BASE_URL` | Used to build links in emails |
| `EMAIL_BACKEND` and SMTP/SES settings | Email delivery |

---

## 15. MVP Scope

**In scope**
- Sign-up, email verification, login and logout, token refresh, password reset and change, email change, account deletion
- Profile (display name, bio)
- Avatars: presigned upload, validation and re-encoding, list, delete, set current (max 5 MB, max 10 per user)
- Public `/avatar/{email_hash}` with fixed sizes and 404, default or identicon fallback
- `derived/` cache in S3
- CDN caching plus invalidation (Varnish locally, CloudFront when hosted)
- Rate limits, report endpoint, Django admin moderation
- A Docker Compose setup that runs the whole application locally (hosting and real CDN come later)

**Future considerations**
- Arbitrary image sizes (`s=1..2048`)
- API keys and per-app rate limits for third-party apps
- Multiple emails per user
- Social login
- Automated content moderation (e.g. Amazon Rekognition)
- Custom domain with the frontend and API under one parent domain (first-party cookies that also work in Safari), and end-to-end HTTPS
- CI/CD pipeline and managed hosting
- Background job queue for invalidation retries and cleanup
- Image format negotiation (AVIF) and animated images

---

## 16. Learning Experiments

Planned hands-on exercises, since learning is the main goal. Exercises 1 to 4 and 6 to 8 can be done locally with Varnish (CDN) and Silo (S3). Exercise 5 (roles and IAM) and exercise 9 (cost) are AWS-specific and wait until hosting. After hosting, repeating the exercises on CloudFront and real S3 and noting the differences is a learning goal in itself.

1. **CDN hits and misses:** inspect `X-Cache` and `Age` response headers; compare latency on first and later requests.
2. **Cache policies:** change TTLs, the cache key (query strings), and observe the effects.
3. **Invalidation:** change the current avatar, measure how long until the edge updates, and what browsers still hold.
4. **Origin lock:** call the origin directly with and without the secret header.
5. **S3 security:** private bucket, bucket policy, IAM role on EC2, least-privilege policy.
6. **Presigned POST:** try uploading an oversized file or wrong type and see S3 reject it; configure bucket CORS.
7. **Lifecycle rules:** expire `uploads/` after one day; optionally add versioning.
8. **Two-layer caching:** compare CDN hit, S3 `derived/` hit, and full resize latencies.
9. **Cost awareness:** watch requests and data transfer in the AWS billing dashboards.

---

## 17. Implementation Roadmap

### Part A: Local application in Docker (current focus)

1. **Setup:**
   - Repository, `.env.example`, and Docker Compose with `db`, `silo`, `silo-init`, `varnish`, `backend`, `frontend` and `mailpit`.
   - `scripts/init_s3.py`: create the bucket, an application access key restricted to it, the CORS rule and the `uploads/` lifecycle rule, then run the S3 smoke test from section 13.6.
2. **Backend foundation:** Django project, custom user model, Postgres connection, settings per environment, CORS with credentials, S3 settings (internal and public endpoints), OpenAPI schema.
3. **Authentication:** register, verify (via Mailpit), login, refresh cookie, logout, password reset and change, email change, account deletion, rate limits, cleanup command for stale unverified accounts.
4. **Avatars:** presigned POST, confirm and processing pipeline, list, delete, set current.
5. **Public endpoint:** lookup by email hash, fixed sizes, resize, `derived/` cache in S3, fallbacks (default, identicon, 404), cache headers and `ETag`, origin-secret check.
6. **Local CDN:** write `cdn/default.vcl` (cache key, TTLs, `X-Cache`, origin header), implement the invalidation service with a `varnish` backend that sends `BAN`, and call it at every trigger in section 9.4.
7. **Frontend:** auth screens, profile page, avatar management page (upload, list, select, delete).
8. **Quality and hardening:** automated tests (auth flows, upload validation, public endpoint, invalidation), report endpoint and Django admin moderation, and a README with run instructions.

**Definition of done for Part A:** a new user can register, verify through Mailpit, log in, upload several pictures, choose a current one, and see it served through Varnish at `http://localhost:8080/avatar/{email_hash}` at fixed sizes, with `X-Cache` showing MISS then HIT, changing the current avatar invalidating the cached copy, fallbacks working, and all of it running with `docker compose up`.

### Part B: Hosting and AWS (later)

9. **Decide hosting** for the frontend, backend and database, based on what we learned locally.
10. **AWS setup:** account, MFA, budget alert, IAM; create the real S3 bucket(s) and re-run the smoke test, comparing behavior with Silo.
11. **Add CloudFront**, the cache policy, the origin lock and real invalidation (`INVALIDATION_BACKEND=cloudfront`).
12. **Deploy** the Docker images, switch `DATABASE_URL`, enable HTTPS for the API, and configure production cookie settings.
13. **Compare and learn:** repeat the CDN and S3 experiments from section 16 on CloudFront and S3, note the differences from Varnish and Silo, and test the deployed cookie flow in the target browsers.
---

## 18. Open Decisions

*Resolved: the refresh token is an httpOnly, Secure, `SameSite=None` cookie with CORS credentials (a cross-site cookie setup).*

1. **Hosting (deferred until the app works locally):** frontend host, backend host, database host, and how the API gets HTTPS (mandatory because of the `Secure` cookie, see section 10).
2. **Exact size list and default size** (proposed: 40, 80, 160, 320, 640; default 80).
3. **Refresh-token rotation:** proposed on; can be relaxed for simplicity.
4. **Email provider once hosted:** Mailpit is used locally; decide between logging only and Amazon SES later.

---

## 19. Known Limitations (accepted)

- The email hash can be confirmed by anyone who guesses an email.
- Changing the email breaks existing avatar URLs.
- Free-tier constraints: Supabase pauses after 7 days idle, the AWS Free plan ends after 6 months, and free allowances may change.
- Invalidation is eventually consistent, and browsers can still serve a cached avatar for up to the `max-age`.
- The API may be reached over a CDN-to-origin HTTP hop without TLS (acceptable for learning only).
- **Cross-site cookie risk:** the refresh cookie is a third-party cookie. Safari blocks these by default, so login will not persist there (the access token works until it expires, then the user must log in again). Chrome and Firefox currently allow it, but browser cookie policies keep changing, so this may break later without any code change. Test in the target browsers after deployment. A shared parent domain removes this limitation.
- Silo and Varnish approximate S3 and CloudFront but are not identical. IAM and roles, edge locations, CloudFront cache-key and invalidation details, lifecycle timing and error messages can differ, so behavior must be re-checked after moving to AWS.
- Silo is a community-maintained fork of MinIO (AGPL-3.0). It is used only as a local development dependency.
- Moderation is manual.
