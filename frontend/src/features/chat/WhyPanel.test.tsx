import { render, screen } from "@testing-library/react";
import type { Explanation } from "../../services/types";
import { WhyPanel } from "./WhyPanel";

const base: Explanation = {
  intent: "knowledge",
  standalone_question: null,
  queries: [{ attempt: 1, reason: "original", queries: ["Can a premium customer get a refund after 8 days?"] }],
  retrieval_attempts: 1,
  candidates: 12,
  authorized: 9,
  evidence_status: "sufficient",
  evidence_reason: null,
  injections_removed: 1,
  sources: [
    { document_id: "d1", document_title: "premium-support-policy", version_id: "v1", version: 1,
      effective_date: "2026-02-01", passages: 2, cited: true },
    { document_id: "d2", document_title: "refund-policy-2026", version_id: "v2", version: 1,
      effective_date: "2026-01-01", passages: 1, cited: false },
  ],
  set_aside: [{ title: "refund-policy-2024", status: "superseded", reason: "superseded by REF-2026-07 (explicit)" }],
  precedence_notes: ["premium-support-policy is a scoped exception to refund-policy-2026."],
  verification: { checked: true, ok: true, partial: false, problem_count: 0, problem_kinds: [] },
  corrections: 0,
  abstain_reason: null,
  abstain_message: null,
};

describe("WhyPanel", () => {
  it("shows searches, versions, precedence and the citation check", () => {
    render(<WhyPanel explanation={base} />);
    const panel = screen.getByLabelText("Why this answer");
    expect(panel).toHaveTextContent("Why this answer?");
    expect(panel).toHaveTextContent("Searched with your question");
    expect(panel).toHaveTextContent("premium-support-policy v1");
    expect(panel).toHaveTextContent("cited");
    expect(panel).toHaveTextContent("read, not cited");
    expect(panel).toHaveTextContent("Set aside 1 older or outdated version(s): refund-policy-2024 (superseded)");
    expect(panel).toHaveTextContent("1 instruction(s) hidden in documents ignored");
    expect(panel).toHaveTextContent("Every claim was matched to a cited source.");
    expect(panel).not.toHaveTextContent("Why Atlas didn't answer");
  });

  it("explains an abstention and query rewrites", () => {
    render(<WhyPanel explanation={{
      ...base, sources: [], set_aside: [], precedence_notes: [], evidence_status: "weak",
      evidence_reason: "evidence covers only 20% of the question's terms",
      queries: [...base.queries, { attempt: 2, reason: "rewrite", after: "weak", queries: ["stock vesting"] }],
      abstain_reason: "weak_evidence",
      abstain_message: "The best passages only partly matched the question, even after rewriting the search.",
      verification: null,
    }} />);
    const panel = screen.getByLabelText("Why this answer");
    expect(panel).toHaveTextContent("Why Atlas didn't answer");
    expect(panel).toHaveTextContent("even after rewriting the search");
    expect(panel).toHaveTextContent("Rewrote the search because the evidence was weak");
  });

  it("is not shown for greetings", () => {
    const { container } = render(<WhyPanel explanation={{ ...base, intent: "greeting" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
