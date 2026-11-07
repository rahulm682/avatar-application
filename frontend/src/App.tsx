import {
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "./auth";
import { useDocumentTitle } from "./ui";
import Login from "./pages/Login";
import Register from "./pages/Register";
import { CheckEmail, ConfirmEmailChange, VerifyEmail } from "./pages/Verify";
import { ForgotPassword, ResetPassword } from "./pages/Passwords";
import Pictures from "./pages/Pictures";
import Account from "./pages/Account";

function Header() {
  const { status, logout } = useAuth();
  return (
    <header className="topbar">
      <div className="shell topbar__inner">
        <Link to="/" className="brand">
          Avatar Service
        </Link>
        <nav className="nav" aria-label="Main">
          {status === "authenticated" ? (
            <>
              <NavLink to="/pictures">Pictures</NavLink>
              <NavLink to="/account">Account</NavLink>
              <button type="button" onClick={() => void logout()}>
                Log out
              </button>
            </>
          ) : status === "anonymous" ? (
            <>
              <NavLink to="/login">Log in</NavLink>
              <NavLink to="/register">Create account</NavLink>
            </>
          ) : null}
        </nav>
      </div>
    </header>
  );
}

/** Pages that need a logged-in user. Visitors are sent to the log-in page and brought back afterwards. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading")
    return <p className="shell page small">Loading...</p>;
  if (status === "anonymous")
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

/** Log-in and sign-up pages make no sense for someone who is already logged in. */
function GuestOnly({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  if (status === "loading")
    return <p className="shell page small">Loading...</p>;
  if (status === "authenticated") return <Navigate to="/pictures" replace />;
  return <>{children}</>;
}

function NotFound() {
  useDocumentTitle("Page not found");
  return (
    <div className="shell page">
      <h1>Page not found</h1>
      <p className="lede">
        There is nothing at this address.{" "}
        <Link to="/">Go to the Home page</Link>.
      </p>
    </div>
  );
}

export default function App() {
  return (
    <>
      <Header />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/pictures" replace />} />
          <Route
            path="/register"
            element={
              <GuestOnly>
                <Register />
              </GuestOnly>
            }
          />
          <Route
            path="/login"
            element={
              <GuestOnly>
                <Login />
              </GuestOnly>
            }
          />
          <Route path="/check-email" element={<CheckEmail />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route
            path="/confirm-email-change"
            element={<ConfirmEmailChange />}
          />
          <Route
            path="/pictures"
            element={
              <RequireAuth>
                <Pictures />
              </RequireAuth>
            }
          />
          <Route
            path="/account"
            element={
              <RequireAuth>
                <Account />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </>
  );
}
