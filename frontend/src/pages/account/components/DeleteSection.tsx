import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../../../api";
import { useAuth } from "../../../auth";
import {
  Alert,
  PasswordField,
  errorText,
} from "../../../ui";

import type { Message } from "./types";

export default function DeleteSection() {
  const { clearSession } = useAuth();
  const navigate = useNavigate();

  const [password, setPassword] = useState("");
  const [sure, setSure] = useState(false);
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    setBusy(true);
    setMessage(null);

    try {
      await api.deleteAccount(password);

      clearSession();
      navigate("/register", { replace: true });
    } catch (e) {
      setMessage({ kind: "error", text: errorText(e) });
      setBusy(false);
    }
  }

  return (
    <section
      className="section section--danger"
      aria-labelledby="delete-heading"
    >
      <h2 id="delete-heading">Delete account</h2>

      <p>
        Your account and all of your pictures disappear right away: nobody can
        see them and you are logged out everywhere. They are kept for 30 days,
        then permanently removed. Your email address can be used for a new
        account straight away.
      </p>

      <form className="form" onSubmit={onSubmit}>
        {message && <Alert kind={message.kind}>{message.text}</Alert>}

        <PasswordField
          label="Current password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        <label className="checkbox">
          <input
            type="checkbox"
            checked={sure}
            onChange={(e) => setSure(e.target.checked)}
          />

          <span>
            I understand that my account and pictures will be deleted.
          </span>
        </label>

        <div className="actions">
          <button
            type="submit"
            className="btn btn--danger"
            disabled={busy || !sure}
          >
            {busy ? "Deleting..." : "Delete my account"}
          </button>
        </div>
      </form>
    </section>
  );
}