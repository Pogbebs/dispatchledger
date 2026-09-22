import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { ApiError } from "../api";

export default function Login() {
  const { signIn } = useAuth();
  const [slug, setSlug] = useState("gulf-coast");
  const [email, setEmail] = useState("admin@gulf-coast.example.com");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(slug.trim(), email.trim(), password);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not reach the server.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>DispatchLedger</h1>
        <p className="tagline">Fuel distribution operations</p>

        {error && <div className="error">{error}</div>}

        <div className="field">
          <label htmlFor="slug">Company</label>
          <input
            id="slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            autoComplete="organization"
            required
          />
        </div>

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            required
          />
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </div>

        <button className="btn" style={{ width: "100%" }} disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <div className="hint">
          Demo data has two companies. Sign in as one, then the other, and the
          same screens show entirely separate records.
          <br />
          <code>gulf-coast</code> or <code>lone-star</code> &middot;{" "}
          <code>admin@&lt;company&gt;.example.com</code> &middot;{" "}
          <code>demo1234</code>
          <br />
          Swap <code>admin</code> for <code>driver1</code> to see a role with
          fewer permissions.
        </div>
      </form>
    </div>
  );
}
