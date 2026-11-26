import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Logo } from "../components/Layout";
import { ErrorBanner, Spinner } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { apiRequest } from "../services/api";
import { supabase } from "../services/supabase";

/** "Explore the demo": a private anonymous session that joins the sample
 * workspace as a viewer. The server decides which workspace. */
export function DemoPage() {
  const { session, loading, isAnonymous } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (loading || started.current || (session && !isAnonymous)) return;
    started.current = true;
    (async () => {
      let token = session?.access_token;
      if (!token) {
        const { data, error: err } = await supabase.auth.signInAnonymously();
        if (err || !data.session) throw new Error(err?.message ?? "The demo is not available right now.");
        token = data.session.access_token;
      }
      const { organization_id } = await apiRequest<{ organization_id: string }>("/v1/demo/join", token, {
        method: "POST",
      });
      navigate(`/o/${organization_id}/chat`, { replace: true });
    })().catch((e: Error) => setError(e.message));
  }, [loading, session, isAnonymous, navigate]);

  if (session && !isAnonymous) return <Navigate to="/" replace />;
  return (
    <div className="auth">
      <div className="card auth-card">
        <Logo />
        <h1>Demo workspace</h1>
        <p className="muted">
          Sample HR, refund and IT policies with conflicting versions. You can ask questions and
          open sources; uploads are turned off. Your chats are private to this browser session.
        </p>
        <ErrorBanner message={error} />
        {!error ? <Spinner label="Opening the demo" /> : <Link to="/login">Back to sign in</Link>}
      </div>
    </div>
  );
}
