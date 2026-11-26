import type { ReactNode } from "react";
import { formatDate } from "../../components/ui";
import type { Explanation } from "../../services/types";

const QUERY_REASON: Record<string, string> = {
  original: "Searched with your question",
  follow_up: "Rewrote your follow-up as a standalone question",
  rewrite: "Rewrote the search because the evidence was weak",
};

const EVIDENCE: Record<string, string> = {
  sufficient: "Strong: the passages cover the question",
  weak: "Weak: the passages only partly cover the question",
  none: "None found",
  not_needed: "Not needed for this message",
};

/** "Why this answer?": the agent's decisions, shown on demand. Contains no
 * document text, only titles, versions and decisions. */
export function WhyPanel({ explanation: e }: { explanation: Explanation }) {
  if (e.intent === "greeting" || e.intent === "clarify") return null;
  const cited = e.sources.filter((s) => s.cited);
  const read = e.sources.filter((s) => !s.cited);
  return (
    <details className="why" aria-label="Why this answer">
      <summary>Why this answer?</summary>
      <div className="why-body">
        {e.abstain_message && (
          <Section title="Why Atlas didn't answer">
            <p>{e.abstain_message}</p>
            {e.evidence_reason && <p className="muted small">Evidence check: {e.evidence_reason}</p>}
          </Section>
        )}

        <Section title="How it searched">
          <ol className="why-steps">
            {e.queries.map((q, i) => (
              <li key={i}>
                <span>{QUERY_REASON[q.reason] ?? q.reason}</span>
                {q.after && <span className="muted small"> ({q.after})</span>}
                <ul className="why-queries">
                  {q.queries.slice(0, 4).map((text) => <li key={text}><code>{text}</code></li>)}
                </ul>
              </li>
            ))}
          </ol>
          <p className="muted small">
            {e.candidates} passages found · {e.authorized} you can read (rechecked against your permissions)
            {e.injections_removed > 0 && ` · ${e.injections_removed} instruction(s) hidden in documents ignored`}
          </p>
        </Section>

        <Section title="Evidence">
          <p>{EVIDENCE[e.evidence_status ?? ""] ?? e.evidence_status ?? "—"}</p>
        </Section>

        {e.sources.length > 0 && (
          <Section title="Sources and versions">
            <ul className="why-sources">
              {[...cited, ...read].map((s) => (
                <li key={s.version_id}>
                  <strong>{s.document_title}</strong> v{s.version}
                  {s.effective_date && <span className="muted"> · effective {formatDate(s.effective_date)}</span>}
                  <span className="muted small"> · {s.cited ? "cited" : "read, not cited"}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {e.set_aside.length > 0 && (
          <Section title="Conflicts and precedence">
            <p>
              Set aside {e.set_aside.length} older or outdated version(s):{" "}
              {e.set_aside.map((d) => `${d.title} (${d.status})`).join(", ")}. The reasons are in
              the "Sources disagree" box above.
            </p>
          </Section>
        )}

        {e.verification && e.verification.checked && (
          <Section title="Citation check">
            <p>
              {e.verification.ok
                ? "Every claim was matched to a cited source."
                : e.verification.partial
                  ? `Unsupported sentences were removed (${e.verification.problem_kinds.join(", ")}).`
                  : `The draft failed the check (${e.verification.problem_kinds.join(", ")}).`}
              {e.corrections > 0 && ` Rewritten ${e.corrections} time(s) to fix citations.`}
            </p>
          </Section>
        )}
      </div>
    </details>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="why-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}
