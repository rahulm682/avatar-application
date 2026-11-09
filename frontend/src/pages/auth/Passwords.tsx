import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../api";
import {
  Alert,
  PasswordField,
  SubmitButton,
  TextField,
  errorText,
  useDocumentTitle,
} from "../../ui";

export function ForgotPassword() {
  useDocumentTitle("Reset password");

  const [email, setEmail] = useState("");

  const [message, setMessage] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);

  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    setBusy(true);
    setMessage(null);

    try {
      const result = await api.requestPasswordReset(email);

      setMessage({
        kind: "success",
        text: result.detail,
      });
    } catch (e) {
      setMessage({
        kind: "error",
        text: errorText(e),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell page">
      <div>
        <h1>Reset your password</h1>

        <p className="lede">
          Enter your email and we will send a link that lets you choose a new
          password. The link works for one hour.
        </p>
      </div>

      <form className="form" onSubmit={onSubmit}>
        {message && <Alert kind={message.kind}>{message.text}</Alert>}

        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />

        <div className="actions">
          <SubmitButton busy={busy} busyLabel="Sending...">
            Send reset link
          </SubmitButton>

          <Link to="/login">Back to log in</Link>
        </div>
      </form>
    </div>
  );
}

/**
 * Opened from the link in the reset email:
 * /reset-password?uid=...&token=...
 */
export function ResetPassword() {
  useDocumentTitle("Choose a new password");

  const [params] = useSearchParams();

  const uid = params.get("uid");
  const token = params.get("token");

  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    if (!uid || !token) return;

    setBusy(true);
    setError(null);
    setFieldErrors({});

    try {
      await api.confirmPasswordReset(uid, token, password);

      setDone(true);
    } catch (e) {
      const passwordErrors =
        e instanceof ApiError ? e.fieldErrors().new_password : undefined;

      if (passwordErrors) {
        setFieldErrors({ password: passwordErrors });
      } else {
        setError(errorText(e));
      }
    } finally {
      setBusy(false);
    }
  }

  if (!uid || !token) {
    return (
      <div className="shell page">
        <h1>This link is incomplete</h1>

        <p className="lede">
          Open the link from the email exactly as it was sent, or{" "}
          <Link to="/forgot-password">request a new one</Link>.
        </p>
      </div>
    );
  }

  if (done) {
    return (
      <div className="shell page">
        <h1>Password updated</h1>

        <p className="lede">
          You were logged out on every device. Log in with your new password.
        </p>

        <div className="actions">
          <Link className="btn btn--primary" to="/login">
            Log in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="shell page">
      <h1>Choose a new password</h1>

      <form className="form" onSubmit={onSubmit}>
        {error && (
          <Alert kind="error">
            {error} <Link to="/forgot-password">Request a new link</Link>
          </Alert>
        )}

        <PasswordField
          label="New password"
          autoComplete="new-password"
          required
          minLength={10}
          value={password}
          errors={fieldErrors.password}
          hint="At least 10 characters."
          onChange={(e) => setPassword(e.target.value)}
        />

        <div className="actions">
          <SubmitButton busy={busy} busyLabel="Saving...">
            Save new password
          </SubmitButton>
        </div>
      </form>
    </div>
  );
}