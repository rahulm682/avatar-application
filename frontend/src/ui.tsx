import { useEffect, useId, useState } from "react";
import type {
  InputHTMLAttributes,
  ReactNode,
  TextareaHTMLAttributes,
} from "react";

import { ApiError, AVATAR_BASE_URL } from "./api";

export function errorText(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "Something went wrong. Try again.";
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} - Avatar Service`;
  }, [title]);
}

export function Alert({
  kind,
  children,
}: {
  kind: "error" | "success" | "info";
  children: ReactNode;
}) {
  return (
    <div
      className={`alert alert--${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}

function describedBy(
  id: string,
  hint?: string,
  errors?: string[],
): string | undefined {
  const ids = [
    hint ? `${id}-hint` : "",
    errors && errors.length > 0 ? `${id}-error` : "",
  ].filter(Boolean);
  return ids.length > 0 ? ids.join(" ") : undefined;
}

function FieldNotes({
  id,
  hint,
  errors,
}: {
  id: string;
  hint?: string;
  errors?: string[];
}) {
  return (
    <>
      {hint && (
        <p className="field__hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      {errors && errors.length > 0 && (
        <ul className="field__errors" id={`${id}-error`}>
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
    </>
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  errors?: string[];
}

export function TextField({
  label,
  hint,
  errors,
  ...input
}: FieldProps & Omit<InputHTMLAttributes<HTMLInputElement>, "id">) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        aria-invalid={errors && errors.length > 0 ? true : undefined}
        aria-describedby={describedBy(id, hint, errors)}
        {...input}
      />
      <FieldNotes id={id} hint={hint} errors={errors} />
    </div>
  );
}

export function TextAreaField({
  label,
  hint,
  errors,
  ...input
}: FieldProps & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "id">) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        aria-invalid={errors && errors.length > 0 ? true : undefined}
        aria-describedby={describedBy(id, hint, errors)}
        {...input}
      />
      <FieldNotes id={id} hint={hint} errors={errors} />
    </div>
  );
}

export function PasswordField({
  label,
  hint,
  errors,
  ...input
}: FieldProps & Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "type">) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="field__password">
        <input
          id={id}
          type={visible ? "text" : "password"}
          aria-invalid={errors && errors.length > 0 ? true : undefined}
          aria-describedby={describedBy(id, hint, errors)}
          {...input}
        />
        <button
          type="button"
          className="btn btn--text"
          aria-pressed={visible}
          onClick={() => setVisible(!visible)}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
      <FieldNotes id={id} hint={hint} errors={errors} />
    </div>
  );
}

export function SubmitButton({
  busy,
  children,
  busyLabel,
}: {
  busy: boolean;
  children: ReactNode;
  busyLabel?: string;
}) {
  return (
    <button type="submit" className="btn btn--primary" disabled={busy}>
      {busy ? (busyLabel ?? "Working...") : children}
    </button>
  );
}

// Some default icons that are displayed on login and register page
// Real identicons from this app's own public endpoint (the hashes are SHA-256 of these sample addresses).
const SAMPLE_HASHES = [
  "b5fc85e55755f9e0d030a10ab4429b6b2944855f9a0d60077fe832becbc41d72",
  "b533d4547eaa5a0fa955965a1ca393ccd2ea013032a105726f232eb41bddc4fa",
  "61356ceff7537431960452071a97f980415f71b0ce1ab92da45f5b5a41277d26",
  "8c681af7d4e5ee66acdec35f1c2c3f1a1ccb76f30c1b052cbe852d8647378369",
  "09eafe4c2b195fc27f6f2dbeaf7f15aec6b293a22356951db37b56ca8c3e7c7e",
  "6a4299746154b9568ca84dc0d3973d3d1d7a38f472ecf0d0338112bf214ad590",
];

export function IdenticonRow() {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;
  return (
    <div className="identicons" aria-hidden="true">
      {SAMPLE_HASHES.map((hash) => (
        <img
          key={hash}
          src={`${AVATAR_BASE_URL}/avatar/${hash}?s=80&d=identicon`}
          alt=""
          width={56}
          height={56}
          onError={() => setHidden(true)}
        />
      ))}
    </div>
  );
}
