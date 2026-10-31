import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "../api";
import {
  Alert,
  IdenticonRow,
  PasswordField,
  SubmitButton,
  TextField,
  errorText,
  useDocumentTitle,
} from "../ui";

export default function Register() {
  useDocumentTitle("Create account");
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      await api.register(email, password);
      navigate(`/check-email?email=${encodeURIComponent(email)}`);
    } catch (e) {
      if (e instanceof ApiError && Object.keys(e.fieldErrors()).length > 0) {
        setFieldErrors(e.fieldErrors());
      } else {
        setError(errorText(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell page auth">
      <div className="auth__intro">
        <IdenticonRow />
        <h1>Create an account</h1>
        <p className="lede">
          Upload a few pictures, pick one, and any app that knows your email can
          show it.
        </p>
      </div>
      <div className="auth__main">
        <form className="form" onSubmit={onSubmit}>
          {error && <Alert kind="error">{error}</Alert>}
          <TextField
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={email}
            errors={fieldErrors.email}
            hint="We send a confirmation link here. Your pictures are tied to this address."
            onChange={(e) => setEmail(e.target.value)}
          />
          <PasswordField
            label="Password"
            autoComplete="new-password"
            required
            minLength={10}
            value={password}
            errors={fieldErrors.password}
            hint="At least 10 characters."
            onChange={(e) => setPassword(e.target.value)}
          />
          <div className="actions">
            <SubmitButton busy={busy} busyLabel="Creating account...">
              Create account
            </SubmitButton>
          </div>
        </form>
        <div className="auth__links">
          <span>
            Already have an account? <Link to="/login">Log in</Link>
          </span>
        </div>
      </div>
    </div>
  );
}
