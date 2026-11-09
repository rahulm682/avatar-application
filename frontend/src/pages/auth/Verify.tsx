import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../../api";
import { useAuth } from "../../auth";
import { Alert, TextField, errorText, useDocumentTitle } from "../../ui";

/**
 * Shown after sign-up: "check your inbox", with a way to send the link again.
 */
export function CheckEmail() {
  useDocumentTitle("Check your email");

  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [message, setMessage] = useState<{
    kind: "success" | "error";
    text: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;

    const timer = window.setTimeout(
      () => setCooldown(cooldown - 1),
      1000,
    );

    return () => window.clearTimeout(timer);
  }, [cooldown]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();

    setBusy(true);
    setMessage(null);

    try {
      const result = await api.resendVerification(email);

      setMessage({
        kind: "success",
        text: result.detail,
      });

      setCooldown(60);
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
        <h1>Check your email</h1>

        <p className="lede">
          {params.get("email") ? (
            <>
              We sent a confirmation link to{" "}
              <strong>{params.get("email")}</strong>. Open it to finish creating
              your account. You can log in once it is confirmed.
            </>
          ) : (
            "Open the confirmation link we sent you to finish creating your account. You can log in once it is confirmed."
          )}
        </p>
      </div>

      <form className="form" onSubmit={onSubmit}>
        <h2>Send the link again</h2>

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
          <button
            type="submit"
            className="btn btn--secondary"
            disabled={busy || cooldown > 0}
          >
            {busy
              ? "Sending..."
              : cooldown > 0
                ? `Send again in ${cooldown}s`
                : "Send the link again"}
          </button>

          <Link to="/login">Back to log in</Link>
        </div>
      </form>
    </div>
  );
}

type LinkState = "working" | "done" | "failed";

/**
 * Opened from the link in the confirmation email:
 * /verify-email?token=...
 */
export function VerifyEmail() {
  useDocumentTitle("Confirm email");

  const [params] = useSearchParams();
  const token = params.get("token");

  const [state, setState] = useState<LinkState>(
    token ? "working" : "failed",
  );
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;

    // React's development mode runs effects twice; confirm only once.
    started.current = true;

    api
      .verifyEmail(token)
      .then((result) => {
        setMessage(result.detail);
        setState("done");
      })
      .catch((e) => {
        setMessage(errorText(e));
        setState("failed");
      });
  }, [token]);

  return (
    <div className="shell page">
      {state === "working" && <h1>Confirming your email...</h1>}

      {state === "done" && (
        <>
          <h1>Email confirmed</h1>

          <p className="lede">{message}</p>

          <div className="actions">
            <Link className="btn btn--primary" to="/login">
              Log in
            </Link>
          </div>
        </>
      )}

      {state === "failed" && (
        <>
          <h1>This link did not work</h1>

          <p className="lede">
            {token
              ? message ||
                "It may have expired, or it was already replaced by a newer one."
              : "The link is incomplete."}
          </p>

          <div className="actions">
            <Link className="btn btn--primary" to="/check-email">
              Get a new link
            </Link>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Opened from the link sent to the NEW address:
 * /confirm-email-change?token=...
 */
export function ConfirmEmailChange() {
  useDocumentTitle("Confirm new email");

  const [params] = useSearchParams();
  const token = params.get("token");

  const { status, reloadUser } = useAuth();

  const [state, setState] = useState<LinkState>(
    token ? "working" : "failed",
  );
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    if (!token || status === "loading" || started.current) return;

    started.current = true;

    api
      .confirmEmailChange(token)
      .then(async (result) => {
        setMessage(result.detail);

        if (status === "authenticated") {
          await reloadUser();
        }

        setState("done");
      })
      .catch((e) => {
        setMessage(errorText(e));
        setState("failed");
      });
  }, [token, status, reloadUser]);

  return (
    <div className="shell page">
      {state === "working" && <h1>Confirming your new email...</h1>}

      {state === "done" && (
        <>
          <h1>Email updated</h1>

          <p className="lede">
            {message} The public picture address is built from your email, so it
            changed with it. Apps that saved the old address will show the
            default picture.
          </p>

          <div className="actions">
            <Link
              className="btn btn--primary"
              to={status === "authenticated" ? "/pictures" : "/login"}
            >
              {status === "authenticated" ? "Go to your pictures" : "Log in"}
            </Link>
          </div>
        </>
      )}

      {state === "failed" && (
        <>
          <h1>This link did not work</h1>

          <p className="lede">
            {token
              ? message || "It may have expired or was already used."
              : "The link is incomplete."}{" "}
            Start the change again from your account page.
          </p>

          <div className="actions">
            <Link className="btn btn--primary" to="/account">
              Go to your account
            </Link>
          </div>
        </>
      )}
    </div>
  );
}