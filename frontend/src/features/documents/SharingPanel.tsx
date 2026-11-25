import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Badge, ErrorBanner } from "../../components/ui";
import { apiRequest } from "../../services/api";
import { can } from "../../services/permissions";
import type { DocumentAccess, DocumentItem, DocumentPermission, Member } from "../../services/types";

/** Rename, change visibility and share one document. Shown only with write
 * access; the API and Postgres RLS enforce every rule regardless. */
export function SharingPanel(props: {
  doc: DocumentItem;
  orgId: string;
  token: string | null;
  onChanged: () => Promise<void> | void;
}) {
  const { doc, orgId, token } = props;
  const base = `/v1/organizations/${orgId}/documents/${doc.id}`;
  const [title, setTitle] = useState(doc.title);
  const [perms, setPerms] = useState<DocumentPermission[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [target, setTarget] = useState("");
  const [level, setLevel] = useState<DocumentAccess>("read");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, m] = await Promise.all([
        apiRequest<DocumentPermission[]>(`${base}/permissions`, token),
        apiRequest<Member[]>(`/v1/organizations/${orgId}/members`, token),
      ]);
      setPerms(p);
      setMembers(m);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [base, orgId, token]);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => setTitle(doc.title), [doc.title]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
      await props.onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const targets = can.shareTargets(members, doc, perms.map((p) => p.user_id));
  const targetMember = targets.find((m) => m.user_id === target);
  const levels = targetMember ? can.grantLevels(targetMember.role) : can.grantLevels("member");

  function share(e: FormEvent) {
    e.preventDefault();
    if (!target) return;
    const permission = levels.includes(level) ? level : "read";
    void run(() => apiRequest(`${base}/permissions/${target}`, token, { method: "PUT", body: { permission } }));
    setTarget("");
  }

  function rename(e: FormEvent) {
    e.preventDefault();
    const t = title.trim();
    if (t && t !== doc.title) void run(() => apiRequest(base, token, { method: "PATCH", body: { title: t } }));
  }

  function changeVisibility(visibility: string) {
    if (
      visibility === "organization" &&
      !window.confirm("Everyone in the workspace will be able to read and search this document.")
    ) {
      return;
    }
    void run(() => apiRequest(base, token, { method: "PATCH", body: { visibility } }));
  }

  return (
    <div className="card sharing" aria-label="Sharing">
      <ErrorBanner message={error} />
      <form className="row wrap" onSubmit={rename}>
        <label className="row small">
          Title
          <input aria-label="Document title" value={title} maxLength={300} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <button className="btn" disabled={!title.trim() || title.trim() === doc.title}>Rename</button>
        <label className="row small">
          Who can see it
          <select aria-label="Document visibility" value={doc.visibility} onChange={(e) => changeVisibility(e.target.value)}>
            <option value="organization">Everyone in the workspace</option>
            <option value="restricted">Only people with access</option>
          </select>
        </label>
      </form>

      <h4>Shared with</h4>
      {perms.length === 0 ? (
        <p className="muted small">
          {doc.visibility === "restricted"
            ? "Only the uploader can see this document."
            : "Nobody has extra access. Sharing matters most for restricted documents."}
        </p>
      ) : (
        <table className="table compact" aria-label="Document permissions">
          <thead><tr><th>Member</th><th>Role</th><th>Access</th><th /></tr></thead>
          <tbody>
            {perms.map((p) => {
              const who = p.email ?? p.user_id;
              const url = `${base}/permissions/${p.user_id}`;
              return (
                <tr key={p.user_id}>
                  <td>{who}{p.member_status !== "active" && <Badge tone="slate">revoked</Badge>}</td>
                  <td>{p.role}</td>
                  <td>
                    <select aria-label={`Access for ${who}`} value={p.permission}
                      onChange={(e) => void run(() => apiRequest(url, token, { method: "PUT", body: { permission: e.target.value } }))}>
                      {can.grantLevels(p.role).map((l) => <option key={l} value={l}>{l}</option>)}
                    </select>
                  </td>
                  <td>
                    <button className="btn btn-ghost" aria-label={`Remove access for ${who}`}
                      onClick={() => void run(() => apiRequest(url, token, { method: "DELETE" }))}>
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {targets.length > 0 && (
        <form className="row wrap" onSubmit={share} aria-label="Share document">
          <select aria-label="Member to share with" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Choose a member…</option>
            {targets.map((m) => (
              <option key={m.user_id} value={m.user_id}>{m.email ?? m.user_id} ({m.role})</option>
            ))}
          </select>
          <select aria-label="Access level" value={level} onChange={(e) => setLevel(e.target.value as DocumentAccess)}>
            {levels.map((l) => <option key={l} value={l}>{l === "read" ? "Can read" : "Can edit and share"}</option>)}
          </select>
          <button className="btn btn-primary" disabled={!target}>Share</button>
        </form>
      )}
    </div>
  );
}
