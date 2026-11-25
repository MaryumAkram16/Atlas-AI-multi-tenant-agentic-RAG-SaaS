import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useOrgs } from "../hooks/useOrgs";
import { can } from "../services/permissions";
import { Badge } from "./ui";

export function Logo() {
  return (
    <span className="logo">
      <span className="logo-mark" aria-hidden>
        ◆
      </span>
      Atlas AI
    </span>
  );
}

export function Layout() {
  const { orgId } = useParams();
  const { orgs } = useOrgs();
  const { email, signOut } = useAuth();
  const navigate = useNavigate();
  const org = orgs.find((o) => o.id === orgId);

  return (
    <div className="shell">
      <aside className="sidebar">
        <Logo />
        <label className="field">
          <span className="field-label">Workspace</span>
          <select
            aria-label="Workspace"
            value={orgId}
            onChange={(e) =>
              e.target.value === "__new" ? navigate("/workspaces") : navigate(`/o/${e.target.value}/chat`)
            }
          >
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
            <option value="__new">+ New workspace</option>
          </select>
        </label>
        {org && (
          <nav className="nav">
            <NavLink to={`/o/${org.id}/chat`}>Chat</NavLink>
            <NavLink to={`/o/${org.id}/documents`}>Knowledge base</NavLink>
            {can.manageMembers(org.role) && <NavLink to={`/o/${org.id}/members`}>Members</NavLink>}
          </nav>
        )}
        <div className="sidebar-foot">
          {org && <Badge tone="slate">{org.role}</Badge>}
          <span className="muted small" title={email ?? ""}>
            {email}
          </span>
          <button className="btn btn-ghost" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </aside>
      <main className="main">
        {org ? <Outlet context={org} /> : <p className="muted">Workspace not found.</p>}
      </main>
    </div>
  );
}
