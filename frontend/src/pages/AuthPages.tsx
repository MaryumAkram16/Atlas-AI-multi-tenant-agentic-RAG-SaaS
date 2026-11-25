import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Logo } from "../components/Layout";
import { ErrorBanner } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { config } from "../services/config";
import { supabase } from "../services/supabase";

function safeNext(next: string | null): string {
  // Only same-app relative paths: never redirect to another origin.
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const navigate = useNavigate();
  const { session } = useAuth();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  if (session) return <Navigate to={next} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { data, error: err } =
      mode === "login"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password });
    setBusy(false);
    if (err) return setError(err.message);
    if (mode === "signup" && !data.session) {
      return setNotice("Check your email to confirm your account, then sign in.");
    }
    navigate(next, { replace: true });
  }

  const other = mode === "login" ? "signup" : "login";
  const query = params.toString() ? `?${params.toString()}` : "";
  return (
    <div className="auth">
      <form className="card auth-card" onSubmit={submit}>
        <Logo />
        <h1>{mode === "login" ? "Sign in" : "Create your account"}</h1>
        <p className="muted">Grounded answers from your organization's documents.</p>
        {!config.configured && (
          <div className="banner banner-info" role="status">
            This deployment isn't connected to a backend yet, so sign-in is unavailable.
          </div>
        )}
        <ErrorBanner message={error} />
        {notice && <div className="banner banner-info">{notice}</div>}
        <label className="field">
          <span className="field-label">Email</span>
          <input type="email" required autoComplete="email" value={email}
            onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">Password</span>
          <input type="password" required minLength={8}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button className="btn btn-primary" disabled={busy || !config.configured} type="submit">
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Sign up"}
        </button>
        <p className="muted small">
          {mode === "login" ? "New to Atlas AI? " : "Already have an account? "}
          <Link to={`/${other}${query}`}>{mode === "login" ? "Create an account" : "Sign in"}</Link>
        </p>
      </form>
    </div>
  );
}

export const LoginPage = () => <AuthForm mode="login" />;
export const SignupPage = () => <AuthForm mode="signup" />;
