import { useEffect, useState } from "react";
import { ErrorBanner, Spinner, formatDate } from "../../components/ui";
import { apiRequest } from "../../services/api";
import type { ChunkPreview, Citation } from "../../services/types";

export function SourcePreview({ orgId, citation, token, onClose }: {
  orgId: string;
  citation: Citation;
  token: string | null;
  onClose: () => void;
}) {
  const [chunk, setChunk] = useState<ChunkPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = `/v1/organizations/${orgId}/documents/${citation.document_id}`;

  useEffect(() => {
    setChunk(null);
    setError(null);
    apiRequest<ChunkPreview>(`${base}/chunks/${citation.chunk_id}`, token)
      .then(setChunk)
      .catch((e: Error) => setError(e.message));
  }, [base, citation.chunk_id, token]);

  async function openOriginal() {
    const { url } = await apiRequest<{ url: string }>(`${base}/versions/${citation.version_id}/download-url`, token);
    window.open(url, "_blank", "noopener");
  }

  return (
    <aside className="preview" aria-label="Source preview">
      <header className="row between">
        <strong>Source {citation.position}</strong>
        <button className="btn btn-ghost" onClick={onClose} aria-label="Close preview">✕</button>
      </header>
      <h3>{citation.document_title}</h3>
      <p className="muted small">
        Version {citation.version} · effective {formatDate(citation.effective_date)}
        {citation.section && <> · {citation.section}</>}
        {citation.page_start && <> · page {citation.page_start}</>}
      </p>
      {(chunk ? chunk.is_current === false : citation.is_current === false) && (
        <p className="banner banner-info small" role="note">
          Older version.{" "}
          {chunk?.current_version
            ? `Version ${chunk.current_version}${chunk.current_effective_date ? `, effective ${formatDate(chunk.current_effective_date)},` : ""} is now current.`
            : "A newer version is now current."}
        </p>
      )}
      <ErrorBanner message={error} />
      {!chunk && !error && <Spinner />}
      {/* Rendered as plain text: document content is untrusted. */}
      {chunk && <blockquote className="excerpt">{chunk.content}</blockquote>}
      <button className="btn" onClick={() => void openOriginal()}>Open original</button>
    </aside>
  );
}
