import { useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../../../api";
import { useAuth } from "../../../auth";
import {
  Alert,
  PasswordField,
  SubmitButton,
  TextField,
  errorText,
} from "../../../ui";

import type { Message } from "./types";

export default function EmailSection() {
  const { user } = useAuth();

  const [newEmail, setNewEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    setBusy(true);
    setMessage(null);
    setFieldErrors({});

    try {
      const result = await api.requestEmailChange(newEmail, password);

      setMessage({ kind: "success", text: result.detail });
      setPassword("");
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
    <section className="section" aria-labelledby="email-heading">
      <h2 id="email-heading">Email address</h2>

      <p>
        Your email is <strong>{user?.email}</strong>. Your public picture
        address is built from it, so changing it changes that address: apps
        that saved the old one will show the default picture.
      </p>

      <form className="form" onSubmit={onSubmit}>
        {message && <Alert kind={message.kind}>{message.text}</Alert>}

        <TextField
          label="New email"
          type="email"
          autoComplete="email"
          required
          value={newEmail}
          errors={fieldErrors.new_email}
          onChange={(e) => setNewEmail(e.target.value)}
        />

        <PasswordField
          label="Current password"
          autoComplete="current-password"
          required
          value={password}
          errors={fieldErrors.password}
          onChange={(e) => setPassword(e.target.value)}
        />

        <div className="actions">
          <SubmitButton busy={busy} busyLabel="Sending...">
            Send confirmation link
          </SubmitButton>
        </div>
      </form>
    </section>
  );
}