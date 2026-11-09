import { useState } from "react";
import type { FormEvent } from "react";

import { ApiError, api } from "../../../api";
import { useAuth } from "../../../auth";
import {
  Alert,
  SubmitButton,
  TextAreaField,
  TextField,
  errorText,
} from "../../../ui";

import type { Message } from "./types";

export default function ProfileSection() {
  const { user, setUser } = useAuth();

  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [bio, setBio] = useState(user?.bio ?? "");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState<Message>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    setBusy(true);
    setMessage(null);
    setFieldErrors({});

    try {
      setUser(await api.updateMe({ display_name: displayName, bio }));
      setMessage({ kind: "success", text: "Changes saved." });
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
    <section className="section" aria-labelledby="profile-heading">
      <h2 id="profile-heading">Profile</h2>

      <form className="form" onSubmit={onSubmit}>
        {message && <Alert kind={message.kind}>{message.text}</Alert>}

        <TextField
          label="Display name"
          maxLength={80}
          value={displayName}
          errors={fieldErrors.display_name}
          onChange={(e) => setDisplayName(e.target.value)}
        />

        <TextAreaField
          label="About you"
          maxLength={500}
          value={bio}
          errors={fieldErrors.bio}
          hint="Up to 500 characters."
          onChange={(e) => setBio(e.target.value)}
        />

        <div className="actions">
          <SubmitButton busy={busy} busyLabel="Saving...">
            Save changes
          </SubmitButton>
        </div>
      </form>
    </section>
  );
}
