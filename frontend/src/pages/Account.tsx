import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api, avatarUrl } from "../api";
import { useAuth } from "../auth";
import {
  Alert,
  PasswordField,
  SubmitButton,
  TextAreaField,
  TextField,
  errorText,
  useDocumentTitle,
} from "../ui";

type Message = { kind: "success" | "error"; text: string } | null;

function ProfileSection() {
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
      if (e instanceof ApiError && Object.keys(e.fieldErrors()).length > 0)
        setFieldErrors(e.fieldErrors());
      else setMessage({ kind: "error", text: errorText(e) });
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

function EmailSection() {
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
      if (e instanceof ApiError && Object.keys(e.fieldErrors()).length > 0)
        setFieldErrors(e.fieldErrors());
      else setMessage({ kind: "error", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section" aria-labelledby="email-heading">
      <h2 id="email-heading">Email address</h2>
      <p>
        Your email is <strong>{user?.email}</strong>. Your public picture
        address is built from it, so changing it changes that address: apps that
        saved the old one will show the default picture.
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

function PasswordSection() {
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
      if (e instanceof ApiError && Object.keys(e.fieldErrors()).length > 0)
        setFieldErrors(e.fieldErrors());
      else setMessage({ kind: "error", text: errorText(e) });
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

function DeleteSection() {
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

export default function Account() {
  useDocumentTitle("Account");
  const { user } = useAuth();
  return (
    <div className="shell page">
      <div className="identity">
        {user && (
          <img
            src={avatarUrl(user.email_hash, 80)}
            alt=""
            width={64}
            height={64}
          />
        )}
        <div>
          <h1>Account</h1>
          <p className="lede">{user?.email}</p>
        </div>
      </div>
      <div className="sections">
        <ProfileSection />
        <EmailSection />
        <PasswordSection />
        <DeleteSection />
      </div>
    </div>
  );
}
