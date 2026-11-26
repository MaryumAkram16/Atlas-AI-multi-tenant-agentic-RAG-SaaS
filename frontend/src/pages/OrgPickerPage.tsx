import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Logo } from "../components/Layout";
import { Badge, ErrorBanner, Spinner } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { useOrgs } from "../hooks/useOrgs";
import { apiRequest } from "../services/api";
import { slugify } from "../services/permissions";
import type { Organization } from "../services/types";

export function OrgPickerPage({ forceList = false }: { forceList?: boolean }) {
  const { token, email, signOut, isAnonymous } = useAuth();
  const { orgs, loading, refresh } = useOrgs();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loading) return <div className="center"><Spinner /></div>;
  if (!forceList && orgs.length === 1) return <Navigate to={`/o/${orgs[0].id}/chat`} replace />;

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const org = await apiRequest<Organization>("/v1/organizations", token, {
        method: "POST",
        body: { name, slug: slugify(name) || "workspace" },
      });
      await refresh();
      navigate(`/o/${org.id}/documents`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card auth-card wide">
        <Logo />
        <h1>Your workspaces</h1>
        <p className="muted small">{isAnonymous ? "Demo visitor" : `Signed in as ${email}`}</p>
        {orgs.length > 0 && (
          <ul className="list">
            {orgs.map((o) => (
              <li key={o.id}>
                <Link to={`/o/${o.id}/chat`}>{o.name}</Link> <Badge tone="slate">{o.role}</Badge>
              </li>
            ))}
          </ul>
        )}
        {isAnonymous ? (
          <p className="muted">
            Demo visitors can't create workspaces. <Link to="/demo">Back to the demo</Link> or sign
            out and create an account.
          </p>
        ) : (
        <form onSubmit={create} className="stack">
          <h2>Create a workspace</h2>
          <ErrorBanner message={error} />
          <label className="field">
            <span className="field-label">Organization name</span>
            <input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)}
              placeholder="Acme Inc." />
          </label>
          {name && <span className="muted small">Address: {slugify(name) || "workspace"}</span>}
          <button className="btn btn-primary" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create workspace"}
          </button>
        </form>
        )}
        <button className="btn btn-ghost" onClick={() => void signOut()}>Sign out</button>
      </div>
    </div>
  );
}
