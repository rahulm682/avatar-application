import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth";
import {
  Alert,
  IdenticonRow,
  PasswordField,
  SubmitButton,
  TextField,
  errorText,
  useDocumentTitle,
} from "../ui";

export default function Login() {
  useDocumentTitle("Log in");
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from =
    (location.state as { from?: string } | null)?.from ?? "/pictures";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell page auth">
      <div className="auth__intro">
        <IdenticonRow />
        <h1>Log in</h1>
        <p className="lede">
          Manage the pictures that follow you from app to app.
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
            onChange={(e) => setEmail(e.target.value)}
          />
          <PasswordField
            label="Password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <div className="actions">
            <SubmitButton busy={busy} busyLabel="Logging in...">
              Log in
            </SubmitButton>
          </div>
        </form>
        <div className="auth__links">
          <Link to="/forgot-password">Forgot your password?</Link>
          <Link to={`/check-email?email=${encodeURIComponent(email)}`}>
            Did not get the confirmation email?
          </Link>
          <span>
            New here? <Link to="/register">Create an account</Link>
          </span>
        </div>
      </div>
    </div>
  );
}
