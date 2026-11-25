import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useOutletContext } from "react-router-dom";
import { Badge, ErrorBanner, STATUS_TONE, formatDate } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { apiRequest } from "../services/api";
import { can } from "../services/permissions";
import type { Invitation, Member, Organization, Role } from "../services/types";

export function MembersPage() {
  const org = useOutletContext<Organization>();
  const { token, userId } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<Invitation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [link, setLink] = useState<string | null>(null);
  const base = `/v1/organizations/${org.id}`;
  const manager = can.manageMembers(org.role);

  const load = useCallback(async () => {
    try {
      setMembers(await apiRequest<Member[]>(`${base}/members`, token));
      if (manager) setInvites(await apiRequest<Invitation[]>(`${base}/invitations`, token));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [base, token, manager]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function invite(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      const inv = await apiRequest<Invitation>(`${base}/members`, token, {
        method: "POST",
        body: { email, role },
      });
      setLink(`${window.location.origin}/invite/${inv.token}`);
      setEmail("");
    });
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Members</h1>
      </header>
      <ErrorBanner message={error} />

      {manager && (
        <form className="card stack" onSubmit={invite} aria-label="Invite a member">
          <h2>Invite a member</h2>
          <div className="row">
            <input type="email" required placeholder="name@company.com" aria-label="Invite email"
              value={email} onChange={(e) => setEmail(e.target.value)} />
            <select aria-label="Invite role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {can.inviteRoles(org.role).map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <button className="btn btn-primary">Create invitation</button>
          </div>
          {link && (
            <div className="banner banner-info">
              <p>Share this one-time link with the invitee (email delivery is not set up yet):</p>
              <div className="row">
                <input readOnly value={link} aria-label="Invitation link" onFocus={(e) => e.target.select()} />
                <button type="button" className="btn" onClick={() => void navigator.clipboard?.writeText(link)}>
                  Copy
                </button>
              </div>
            </div>
          )}
        </form>
      )}

      <table className="table">
        <thead>
          <tr><th>Member</th><th>Role</th><th>Status</th><th>Joined</th><th /></tr>
        </thead>
        <tbody>
          {members.map((m) => {
            const roles = can.changeRole(org.role, userId ?? "", m);
            return (
              <tr key={m.id}>
                <td>{m.email ?? m.user_id}{m.user_id === userId && <span className="muted"> (you)</span>}</td>
                <td>
                  {roles.length ? (
                    <select aria-label={`Role for ${m.email}`} value={m.role}
                      onChange={(e) => void run(() => apiRequest(`${base}/members/${m.id}`, token, {
                        method: "PATCH", body: { role: e.target.value } }))}>
                      {roles.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  ) : (
                    <Badge tone="slate">{m.role}</Badge>
                  )}
                </td>
                <td><Badge tone={STATUS_TONE[m.status]}>{m.status}</Badge></td>
                <td>{formatDate(m.created_at)}</td>
                <td>
                  {can.revoke(org.role, userId ?? "", m) && (
                    <button className="btn btn-danger" onClick={() => {
                      if (window.confirm(`Revoke access for ${m.email ?? "this member"}?`)) {
                        void run(() => apiRequest(`${base}/members/${m.id}`, token, { method: "DELETE" }));
                      }
                    }}>Revoke</button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {manager && invites.length > 0 && (
        <>
          <h2>Invitations</h2>
          <table className="table">
            <thead><tr><th>Email</th><th>Role</th><th>Status</th><th>Expires</th></tr></thead>
            <tbody>
              {invites.map((i) => (
                <tr key={i.id}>
                  <td>{i.email}</td>
                  <td>{i.role}</td>
                  <td>{i.accepted_at ? "accepted" : i.revoked_at ? "revoked" : "pending"}</td>
                  <td>{formatDate(i.expires_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
