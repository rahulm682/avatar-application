import { useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../../../api";
import {
  Alert,
  PasswordField,
  SubmitButton,
  errorText,
} from "../../../ui";

import type { Message } from "./types";

export default function PasswordSection() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    setBusy(true);
    setMessage(null);
    setFieldErrors({});

    try {
      await api.changePassword(current, next);

      setCurrent("");
      setNext("");

      setMessage({
        kind: "success",
        text: "Password changed. You were logged out on your other devices.",
      });
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors()).length > 0) {
        setFieldErrors(e.fieldErrors());
      } else {
        setMessage({ kind: "error", text: errorText(e) });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section" aria-labelledby="password-heading">
      <h2 id="password-heading">Password</h2>

      <form className="form" onSubmit={onSubmit}>
        {message && <Alert kind={message.kind}>{message.text}</Alert>}

        <PasswordField
          label="Current password"
          autoComplete="current-password"
          required
          value={current}
          errors={fieldErrors.current_password}
          onChange={(e) => setCurrent(e.target.value)}
        />

        <PasswordField
          label="New password"
          autoComplete="new-password"
          required
          minLength={10}
          value={next}
          errors={fieldErrors.new_password}
          hint="At least 10 characters."
          onChange={(e) => setNext(e.target.value)}
        />

        <div className="actions">
          <SubmitButton busy={busy} busyLabel="Saving...">
            Change password
          </SubmitButton>
        </div>
      </form>
    </section>
  );
}