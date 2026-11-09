import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ChangeEvent, DragEvent } from "react";

import { AVATAR_BASE_URL, api, avatarUrl, uploadToStorage } from "../../api";
import type { Picture } from "../../api";
import { useAuth } from "../../auth";
import { Alert, errorText, useDocumentTitle } from "../../ui";

const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 5 * 1024 * 1024;
const SERVED_SIZES = [40, 80, 160, 320]; // the 640 px size exists too; it is just too large to show here

type Notice = { kind: "success" | "error"; text: string } | null;

interface UploadState {
  name: string;
  progress: number;
  phase: "uploading" | "processing";
}

function checkFile(file: File): string | null {
  if (!ACCEPTED_TYPES.includes(file.type))
    return "Choose a PNG, JPEG or WebP picture.";

  if (file.size > MAX_BYTES) return "That file is larger than 5 MB.";

  return null;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** The current picture, and exactly what other applications receive for it. */
function Stage({
  emailHash,
  current,
  version,
  onUseDefault,
  busy,
}: {
  emailHash: string;
  current: Picture | undefined;
  version: number;
  onUseDefault: () => void;
  busy: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const snippet = `<img src="${avatarUrl(emailHash, 160)}" width="80" height="80" alt="">`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be blocked; the text is selectable, so nothing else to do.
    }
  }

  return (
    <section aria-labelledby="current-heading">
      <div className="stage">
        <div className="stage__frame">
          <div className={current ? "frame frame--current" : "frame"}>
            <img
              src={
                current
                  ? current.preview_url
                  : avatarUrl(emailHash, 160, version)
              }
              alt={current ? "Your current picture" : "The default picture"}
            />
            {current && <span className="tag">Current</span>}
          </div>

          {current ? (
            <button
              type="button"
              className="btn btn--text btn--small"
              disabled={busy}
              onClick={onUseDefault}
            >
              Use the default picture
            </button>
          ) : (
            <p className="small">
              You have no current picture, so apps show the default one.
            </p>
          )}
        </div>

        <div>
          <h2 id="current-heading">What other apps receive</h2>

          <p className="lede">
            The same picture, fetched from the CDN at the sizes it serves.
          </p>

          <div className="sizes">
            {SERVED_SIZES.map((size) => (
              <figure key={size}>
                <img
                  src={avatarUrl(emailHash, size, version)}
                  width={size}
                  height={size}
                  alt=""
                />
                <figcaption>{size} px</figcaption>
              </figure>
            ))}
          </div>

          <div className="snippet">
            <code aria-label="HTML for showing this picture">{snippet}</code>

            <button
              type="button"
              className="btn btn--secondary btn--small"
              onClick={() => void copy()}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>

          <p className="small" style={{ marginTop: "0.8rem" }}>
            Any app can build this address from your email: lowercase it, take
            its SHA-256, and put the result after{" "}
            <code>{AVATAR_BASE_URL}/avatar/</code>. Your hash is{" "}
            <code>{emailHash.slice(0, 12)}...</code>
          </p>
        </div>
      </div>
    </section>
  );
}

export default function Pictures() {
  useDocumentTitle("Your pictures");

  const { user } = useAuth();
  const queryClient = useQueryClient();

  const list = useQuery({
    queryKey: ["pictures"],
    queryFn: () => api.listPictures(),
  });

  const [version, setVersion] = useState(() => Date.now());
  const [upload, setUpload] = useState<UploadState | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [dragging, setDragging] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  async function afterChange() {
    setVersion(Date.now()); // new address for the browser, so it does not show a cached copy
    await queryClient.invalidateQueries({ queryKey: ["pictures"] });
  }

  const setCurrent = useMutation({
    mutationFn: (id: string | null) => api.setCurrentPicture(id),

    onSuccess: async (_data, id) => {
      setNotice({
        kind: "success",
        text: id
          ? "That picture is now your current one."
          : "You are using the default picture.",
      });

      await afterChange();
    },

    onError: (e) => setNotice({ kind: "error", text: errorText(e) }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deletePicture(id),

    onSuccess: async () => {
      setConfirmingDelete(null);
      setNotice({ kind: "success", text: "Picture deleted." });

      await afterChange();
    },

    onError: (e) => setNotice({ kind: "error", text: errorText(e) }),
  });

  async function handleFile(file: File) {
    setNotice(null);

    const problem = checkFile(file);

    if (problem) {
      setNotice({ kind: "error", text: problem });
      return;
    }

    setUpload({ name: file.name, progress: 0, phase: "uploading" });

    try {
      // 1. ask the API for a presigned upload,
      // 2. send the file straight to storage,
      // 3. let the API check and register it
      const ticket = await api.getUploadTicket(file.type, file.size);

      await uploadToStorage(ticket, file, (fraction) =>
        setUpload({
          name: file.name,
          progress: fraction,
          phase: "uploading",
        }),
      );

      setUpload({ name: file.name, progress: 1, phase: "processing" });

      const { picture, created } = await api.confirmUpload(ticket.upload_token);

      await afterChange();

      setNotice({
        kind: "success",
        text: !created
          ? "You had already added that picture."
          : picture.is_current
            ? "Picture added. It is now your current picture."
            : "Picture added.",
      });
    } catch (e) {
      setNotice({ kind: "error", text: errorText(e) });
    } finally {
      setUpload(null);
    }
  }

  function onPick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    event.target.value = ""; // so choosing the same file again still triggers a change

    if (file) void handleFile(file);
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);

    const file = event.dataTransfer.files[0];

    if (file && upload === null) void handleFile(file);
  }

  if (!user) return null;

  const pictures = list.data?.results ?? [];
  const max = list.data?.max_avatars ?? 10;
  const current = pictures.find((picture) => picture.is_current);
  const limitReached = pictures.length >= max;
  const addDisabled = upload !== null || limitReached;

  return (
    <div className="shell page">
      <div>
        <h1>Your pictures</h1>

        <p className="lede">
          The picture marked as current is what other apps show for {user.email}
          .
        </p>
      </div>

      <Stage
        emailHash={user.email_hash}
        current={current}
        version={version}
        busy={setCurrent.isPending}
        onUseDefault={() => setCurrent.mutate(null)}
      />

      <section aria-labelledby="gallery-heading">
        <div className="section-head">
          <h2 id="gallery-heading">All pictures</h2>

          {list.data && (
            <span className="small">
              {pictures.length} of {max}
            </span>
          )}
        </div>

        {notice && <Alert kind={notice.kind}>{notice.text}</Alert>}

        {list.isError && (
          <Alert kind="error">
            {errorText(list.error)}{" "}
            <button
              type="button"
              className="btn btn--text btn--small"
              onClick={() => void list.refetch()}
            >
              Try again
            </button>
          </Alert>
        )}

        {list.isPending && <p className="small">Loading your pictures...</p>}

        {list.data && (
          <ul className="grid" style={{ marginTop: notice ? "1.2rem" : 0 }}>
            <li>
              <label
                className={`tile-add${dragging ? " is-dragging" : ""}${addDisabled ? " is-disabled" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();

                  if (!addDisabled) setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
              >
                <input
                  className="visually-hidden"
                  type="file"
                  accept={ACCEPTED_TYPES.join(",")}
                  disabled={addDisabled}
                  onChange={onPick}
                />

                {upload ? (
                  <>
                    <strong>
                      {upload.phase === "uploading"
                        ? "Uploading..."
                        : "Checking the picture..."}
                    </strong>

                    <span className="small">{upload.name}</span>

                    <div
                      className="progress"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(upload.progress * 100)}
                    >
                      <div
                        style={{
                          width: `${Math.round(upload.progress * 100)}%`,
                        }}
                      />
                    </div>
                  </>
                ) : limitReached ? (
                  <>
                    <strong>Limit reached</strong>

                    <span className="small">
                      Delete a picture to add another.
                    </span>
                  </>
                ) : (
                  <>
                    <strong>Add a picture</strong>

                    <span className="small">
                      Drop a file here or choose one. PNG, JPEG or WebP, up to 5
                      MB.
                    </span>
                  </>
                )}
              </label>
            </li>

            {pictures.map((picture) => (
              <li key={picture.id} className="picture">
                <div
                  className={
                    picture.is_current ? "frame frame--current" : "frame"
                  }
                >
                  <img
                    src={picture.preview_url}
                    alt={`Picture added ${formatDate(picture.created_at)}`}
                    loading="lazy"
                  />

                  {picture.is_current && <span className="tag">Current</span>}
                </div>

                <p className="picture__meta">
                  {picture.width} x {picture.height}, added{" "}
                  {formatDate(picture.created_at)}
                </p>

                <div className="picture__actions">
                  {!picture.is_current && (
                    <button
                      type="button"
                      className="btn btn--secondary btn--small"
                      disabled={setCurrent.isPending}
                      onClick={() => setCurrent.mutate(picture.id)}
                    >
                      Use as current
                    </button>
                  )}

                  {confirmingDelete === picture.id ? (
                    <>
                      <button
                        type="button"
                        className="btn btn--danger-solid btn--small"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(picture.id)}
                      >
                        Delete picture
                      </button>

                      <button
                        type="button"
                        className="btn btn--text btn--small"
                        onClick={() => setConfirmingDelete(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="btn btn--danger btn--small"
                      onClick={() => setConfirmingDelete(picture.id)}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {list.data && pictures.length === 0 && (
          <p className="empty" style={{ marginTop: "1.2rem" }}>
            No pictures yet. Add one and it becomes your picture right away.
          </p>
        )}
      </section>
    </div>
  );
}
