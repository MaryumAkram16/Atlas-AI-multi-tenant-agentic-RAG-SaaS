import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useOutletContext } from "react-router-dom";
import { Badge, EmptyState, ErrorBanner, STATUS_TONE, formatDate } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { usePolling } from "../hooks/usePolling";
import { ApiError, apiRequest } from "../services/api";
import { can } from "../services/permissions";
import type { DocumentItem, Organization, UploadAccepted } from "../services/types";

const ACCEPT = ".pdf,.docx,.txt,.md";

export function KnowledgeBasePage() {
  const org = useOutletContext<Organization>();
  const { token, userId } = useAuth();
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [open, setOpen] = useState<DocumentItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const base = `/v1/organizations/${org.id}/documents`;

  const load = useCallback(async () => {
    try {
      setDocs(await apiRequest<DocumentItem[]>(base, token));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [base, token]);

  const loadDetail = useCallback(
    async (id: string) => setOpen(await apiRequest<DocumentItem>(`${base}/${id}`, token)),
    [base, token],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const busy = docs.some((d) => d.status === "processing" || d.status === "deleting");
  usePolling(() => {
    void load();
    if (open) void loadDetail(open.id).catch(() => setOpen(null));
  }, 2000, busy);

  async function act(action: () => Promise<unknown>, done?: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      if (done) setNotice(done);
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.code === "duplicate_document") {
        setError("This exact file is already in the knowledge base.");
      } else {
        setError((e as Error).message);
      }
    }
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>Knowledge base</h1>
        <span className="muted small">PDF, DOCX, TXT and Markdown</span>
      </header>
      <ErrorBanner message={error} />
      {notice && <div className="banner banner-info">{notice}</div>}
      {can.upload(org.role) && (
        <UploadForm onUpload={(form) => act(() => apiRequest<UploadAccepted>(base, token, {
          method: "POST", body: form }), "Uploaded. Indexing has started.")} />
      )}

      {docs.length === 0 ? (
        <EmptyState title="No documents yet">
          <p className="muted">
            {can.upload(org.role) ? "Upload a policy or handbook to start asking questions."
              : "Ask a member to upload documents."}
          </p>
        </EmptyState>
      ) : (
        <table className="table" aria-label="Documents">
          <thead>
            <tr><th>Title</th><th>Status</th><th>Version</th><th>Effective</th><th>Chunks</th><th>Updated</th></tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <Fragment key={d.id}>
                <tr className="clickable" onClick={() => (open?.id === d.id ? setOpen(null) : void loadDetail(d.id))}>
                  <td>
                    {d.title}
                    {d.visibility === "restricted" && <Badge tone="violet">restricted</Badge>}
                  </td>
                  <td><Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge></td>
                  <td>{d.current_version ? `v${d.current_version.version}` : "—"}</td>
                  <td>{formatDate(d.current_version?.effective_date)}</td>
                  <td>{d.current_version?.chunk_count ?? "—"}</td>
                  <td>{formatDate(d.updated_at)}</td>
                </tr>
                {open?.id === d.id && (
                  <tr>
                    <td colSpan={6}>
                      <DocumentDetail doc={open} canWrite={can.writeDocument(org.role, userId ?? "", d.owner_id)}
                        onVersion={(form) => act(() => apiRequest(`${base}/${d.id}/versions`, token, {
                          method: "POST", body: form }), "New version uploaded. Indexing has started.")}
                        onReindex={() => act(() => apiRequest(`${base}/${d.id}/reindex`, token,
                          { method: "POST" }), "Reindexing started.")}
                        onDelete={() => {
                          if (window.confirm(`Delete "${d.title}"? This removes it from search.`)) {
                            void act(() => apiRequest(`${base}/${d.id}`, token, { method: "DELETE" }),
                              "Deletion started.");
                            setOpen(null);
                          }
                        }}
                        onDownload={async (versionId) => {
                          const { url } = await apiRequest<{ url: string }>(
                            `${base}/${d.id}/versions/${versionId}/download-url`, token);
                          window.open(url, "_blank", "noopener");
                        }} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function UploadForm({ onUpload }: { onUpload: (form: FormData) => Promise<void> }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [visibility, setVisibility] = useState("organization");
  const [effective, setEffective] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("visibility", visibility);
    if (effective) form.append("effective_date", effective);
    setBusy(true);
    await onUpload(form);
    setBusy(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  return (
    <form className="card row wrap" onSubmit={submit} aria-label="Upload document">
      <input ref={fileRef} type="file" accept={ACCEPT} required aria-label="Document file" />
      <select aria-label="Visibility" value={visibility} onChange={(e) => setVisibility(e.target.value)}>
        <option value="organization">Everyone in the workspace</option>
        <option value="restricted">Only me (restricted)</option>
      </select>
      <label className="row small muted">
        Effective date
        <input type="date" value={effective} onChange={(e) => setEffective(e.target.value)} />
      </label>
      <button className="btn btn-primary" disabled={busy}>{busy ? "Uploading…" : "Upload"}</button>
    </form>
  );
}

function DocumentDetail(props: {
  doc: DocumentItem;
  canWrite: boolean;
  onVersion: (form: FormData) => Promise<void>;
  onReindex: () => void;
  onDelete: () => void;
  onDownload: (versionId: string) => Promise<void>;
}) {
  const { doc, canWrite } = props;
  const fileRef = useRef<HTMLInputElement>(null);
  return (
    <div className="detail">
      <table className="table compact" aria-label="Versions">
        <thead><tr><th>Version</th><th>File</th><th>Status</th><th>Effective</th><th>Uploaded</th><th /></tr></thead>
        <tbody>
          {(doc.versions ?? []).map((v) => (
            <tr key={v.id}>
              <td>v{v.version}</td>
              <td>{v.filename}</td>
              <td>
                <Badge tone={STATUS_TONE[v.status]}>{v.status}</Badge>
                {v.error && <span className="muted small"> {v.error}</span>}
              </td>
              <td>{formatDate(v.effective_date)}</td>
              <td>{formatDate(v.created_at)}</td>
              <td><button className="btn btn-ghost" onClick={() => void props.onDownload(v.id)}>Download</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {canWrite && doc.status !== "deleting" && (
        <div className="row wrap">
          <input ref={fileRef} type="file" accept={ACCEPT} aria-label="New version file" />
          <button className="btn" onClick={() => {
            const file = fileRef.current?.files?.[0];
            if (!file) return;
            const form = new FormData();
            form.append("file", file);
            void props.onVersion(form);
          }}>Upload new version</button>
          <button className="btn" onClick={props.onReindex}>Reindex</button>
          <button className="btn btn-danger" onClick={props.onDelete}>Delete</button>
        </div>
      )}
    </div>
  );
}
