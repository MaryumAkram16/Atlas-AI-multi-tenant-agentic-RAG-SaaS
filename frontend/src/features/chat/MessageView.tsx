import type { ReactNode } from "react";
import { Badge, STATUS_TONE, formatDate } from "../../components/ui";
import type { ChatMessage, Citation, Conflict } from "../../services/types";
import { WhyPanel } from "./WhyPanel";

/** Render answer text with [n] markers turned into clickable citation chips. */
export function AnswerText({ text, citations, onCite }: {
  text: string;
  citations: Citation[];
  onCite: (c: Citation) => void;
}) {
  const byPos = new Map(citations.map((c) => [c.position, c]));
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="answer">
      {parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/);
        const c = m ? byPos.get(Number(m[1])) : undefined;
        return c ? (
          <button key={i} className="cite" onClick={() => onCite(c)} title={`${c.document_title}${c.section ? ` · ${c.section}` : ""}`}>
            {c.position}
          </button>
        ) : (
          <span key={i}>{part}</span>
        );
      })}
    </p>
  );
}

export function ConflictPanel({ conflicts }: { conflicts: Conflict[] }) {
  if (!conflicts.length) return null;
  const ambiguous = conflicts.some((c) => c.resolution === "ambiguous");
  return (
    <div className={`conflicts ${ambiguous ? "conflicts-ambiguous" : ""}`} role="note" aria-label="Conflicting sources">
      <strong>{ambiguous ? "Sources disagree and it is unclear which applies" : "Sources disagree; resolved by precedence"}</strong>
      {conflicts.map((c, i) => (
        <div key={i} className="conflict">
          <ul>
            {c.documents.map((d) => (
              <li key={d.document_id}>
                <Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge> {d.policy_id ?? d.title}
                <span className="muted small"> · {d.values.join(", ")} · effective {formatDate(d.effective_date)}</span>
                {d.reason && <div className="muted small">{d.reason}</div>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

const STATUS_COPY: Record<string, { tone: string; title: string; body: string }> = {
  insufficient_evidence: {
    tone: "abstain",
    title: "Not enough evidence",
    body: "I couldn't find this in documents you can access. Try rephrasing, or ask an admin whether the right document has been uploaded.",
  },
  clarification_needed: {
    tone: "info",
    title: "Could you clarify?",
    body: "Add a bit more detail, such as the policy or topic you mean.",
  },
  error: { tone: "error", title: "Something went wrong", body: "Please try again." },
};

export function MessageView({ message, onCite, footer }: {
  message: ChatMessage;
  onCite: (c: Citation) => void;
  footer?: ReactNode;
}) {
  if (message.role === "user") {
    return <div className="msg msg-user">{message.content}</div>;
  }
  const special = message.status ? STATUS_COPY[message.status] : undefined;
  return (
    <div className={`msg msg-assistant ${special ? `msg-${special.tone}` : ""}`} data-status={message.status ?? ""}>
      {special && <div className="msg-title">{special.title}</div>}
      {special && message.status !== "error" ? (
        <p className="muted">{special.body}</p>
      ) : (
        <AnswerText text={message.content} citations={message.citations} onCite={onCite} />
      )}
      <ConflictPanel conflicts={message.conflicts} />
      {message.explanation && <WhyPanel explanation={message.explanation} />}
      {message.citations.length > 0 && (
        <ol className="sources" aria-label="Sources">
          {message.citations.map((c) => (
            <li key={c.position}>
              <button className="source" onClick={() => onCite(c)}>
                <span className="cite">{c.position}</span>
                <span>
                  {c.document_title} <span className="muted">v{c.version}</span>
                  {c.is_current === false && <Badge tone="slate">older version</Badge>}
                  {c.effective_date && <span className="muted small"> · effective {formatDate(c.effective_date)}</span>}
                  {c.section && <span className="muted small"> · {c.section}</span>}
                  {c.page_start && <span className="muted small"> · p. {c.page_start}{c.page_end && c.page_end !== c.page_start ? `–${c.page_end}` : ""}</span>}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
      {footer}
    </div>
  );
}
