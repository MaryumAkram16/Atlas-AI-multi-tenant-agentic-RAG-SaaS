import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { EmptyState, ErrorBanner } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { apiRequest } from "../services/api";
import { actionLabel } from "../services/format";
import type { AuditLog, Member, Organization } from "../services/types";

const PAGE = 50;
const ACTIONS = [
  "",
  "organization.created",
  "invitation.created",
  "invitation.accepted",
  "invitation.revoked",
  "member.joined",
  "member.role_changed",
  "member.revoked",
  "member.reactivated",
  "document.created",
  "document.version_uploaded",
  "document.version_published",
  "document.visibility_changed",
  "document.reindex_requested",
  "document.deletion_requested",
  "document.deleted",
  "document.permission_granted",
  "document.permission_changed",
  "document.permission_revoked",
  "evaluation.dataset_created",
  "evaluation.dataset_deleted",
  "evaluation.run_started",
];

export function AuditLogPage() {
  const org = useOutletContext<Organization>();
  const { token } = useAuth();
  const [rows, setRows] = useState<AuditLog[]>([]);
  const [members, setMembers] = useState<Record<string, string>>({});
  const [action, setAction] = useState("");
  const [more, setMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/v1/organizations/${org.id}`;

  const fetchPage = useCallback(
    async (beforeId?: number) => {
      const params = new URLSearchParams({ limit: String(PAGE) });
      if (beforeId) params.set("before_id", String(beforeId));
      if (action) params.set("action", action);
      return apiRequest<AuditLog[]>(`${base}/audit-logs?${params}`, token);
    },
    [base, token, action],
  );

  useEffect(() => {
    setError(null);
    fetchPage()
      .then((page) => {
        setRows(page);
        setMore(page.length === PAGE);
      })
      .catch((e: Error) => setError(e.message));
  }, [fetchPage]);

  useEffect(() => {
    apiRequest<Member[]>(`${base}/members`, token)
      .then((list) => setMembers(Object.fromEntries(list.map((m) => [m.user_id, m.email ?? m.user_id]))))
      .catch(() => undefined);
  }, [base, token]);

  async function loadOlder() {
    try {
      const page = await fetchPage(rows[rows.length - 1]?.id);
      setRows((r) => [...r, ...page]);
      setMore(page.length === PAGE);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Audit log</h1>
        <label className="row small muted">
          Action
          <select aria-label="Filter by action" value={action} onChange={(e) => setAction(e.target.value)}>
            {ACTIONS.map((a) => <option key={a} value={a}>{a ? actionLabel(a) : "All actions"}</option>)}
          </select>
        </label>
      </header>
      <ErrorBanner message={error} />
      <p className="muted small">
        Written by the database for every change, whichever path made it. Entries hold IDs and
        roles only, never document text.
      </p>
      {rows.length === 0 ? (
        <EmptyState title="No entries" />
      ) : (
        <table className="table" aria-label="Audit log">
          <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Details</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="nowrap">{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.actor_type === "system" ? "System" : members[r.actor_id ?? ""] ?? "Former member"}</td>
                <td>{actionLabel(r.action)}</td>
                <td className="small muted">{details(r, members)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {more && <button className="btn" onClick={() => void loadOlder()}>Load older</button>}
    </section>
  );
}

function details(r: AuditLog, members: Record<string, string>): string {
  const parts = Object.entries(r.metadata).map(([k, v]) => {
    let value = typeof v === "string" && members[v] ? members[v] : String(v);
    if (/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(value)) value = value.slice(0, 8);
    return `${k.replace(/_/g, " ")}: ${value}`;
  });
  return [`${r.resource_type} ${r.resource_id?.slice(0, 8) ?? ""}`.trim(), ...parts].join(" · ");
}
