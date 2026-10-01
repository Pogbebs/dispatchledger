import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api, setToken } from "../api";

/**
 * Turning an invitation link into an account.
 *
 * The token is in the URL, which is why it is single-use and expiring: a link
 * is a credential that travels through email, gets forwarded, and sits in
 * browser history. Accepting it consumes it.
 *
 * Reached while signed out, so it renders outside the authenticated shell.
 */
export default function AcceptInvite() {
  const { token = "" } = useParams();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Sign out whoever was using this browser before showing the form.
  //
  // An invitation is usually opened in the same window the dispatcher just
  // used to issue it. Their token is still in storage, probably expired, and
  // the app checks it on load -- so a session error from a completely
  // unrelated account appears on this page while someone is trying to set a
  // password, and reads as though the invitation were the problem.
  //
  // Nobody arrives here already signed in on purpose. Clearing it is both
  // correct and the end of a confusing class of report.
  useEffect(() => {
    setToken(null);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();

    // Checked here because the server has no second field to compare, and a
    // mistyped password on a single-use link is an unpleasant way to lose an
    // invitation.
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }

    setBusy(true);
    try {
      const { access_token } = await api.acceptInvite(token, password);
      setToken(access_token);
      // A full reload rather than a route change: the app decides which
      // application to show from /me, and this is the moment that answer
      // changes.
      window.location.href = "/portal/orders";
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not set up your account. Ask your distributor for a new link.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">DispatchLedger</div>
        <h1>Set your password</h1>
        <p className="subtle">
          Your distributor invited you to track your orders and invoices.
        </p>

        {error && <div className="error">{error}</div>}

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
            autoFocus
          />
        </label>

        <label>
          Confirm password
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            minLength={8}
            required
          />
        </label>

        <button className="btn" disabled={busy}>
          {busy ? "Setting up…" : "Create my account"}
        </button>

        <p className="subtle" style={{ fontSize: 12 }}>
          At least 8 characters. This link works once and expires.
        </p>
      </form>
    </div>
  );
}
