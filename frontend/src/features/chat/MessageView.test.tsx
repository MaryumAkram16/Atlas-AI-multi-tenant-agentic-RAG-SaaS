import { fireEvent, render, screen } from "@testing-library/react";
import type { ChatMessage } from "../../services/types";
import { MessageView } from "./MessageView";

const citation = {
  position: 1, chunk_id: "c1", document_id: "d1", document_title: "premium-support-policy",
  version_id: "v1", version: 1, effective_date: "2026-02-01",
  section: "Premium Support Policy > Premium refund exception", page_start: null, page_end: null,
};

const answered: ChatMessage = {
  id: "a", role: "assistant", status: "answered",
  content: "Premium plan customers may request a refund within 10 days [1].",
  citations: [citation],
  conflicts: [{
    topic: "day", resolution: "resolved", notes: [],
    documents: [
      { document_id: "d0", title: "refund-policy-2024", policy_id: "REF-2024-01", effective_date: "2024-01-01",
        values: ["14 day"], status: "superseded", reason: "superseded by REF-2026-07 (explicit)" },
      { document_id: "d1", title: "premium-support-policy", policy_id: "PREM-2026-02", effective_date: "2026-02-01",
        values: ["10 day"], status: "exception", reason: "scoped exception" },
    ],
  }],
};

describe("MessageView", () => {
  it("renders clickable citations and the source list", () => {
    const onCite = vi.fn();
    render(<MessageView message={answered} onCite={onCite} />);
    fireEvent.click(screen.getAllByRole("button", { name: "1" })[0]);
    expect(onCite).toHaveBeenCalledWith(citation);
    expect(screen.getByLabelText("Sources")).toHaveTextContent("premium-support-policy");
  });

  it("shows resolved conflicts with version status", () => {
    render(<MessageView message={answered} onCite={() => {}} />);
    const panel = screen.getByLabelText("Conflicting sources");
    expect(panel).toHaveTextContent("resolved by precedence");
    expect(panel).toHaveTextContent("superseded");
    expect(panel).toHaveTextContent("REF-2024-01");
  });

  it("flags ambiguous conflicts", () => {
    const msg = { ...answered, conflicts: [{ ...answered.conflicts[0], resolution: "ambiguous" as const }] };
    render(<MessageView message={msg} onCite={() => {}} />);
    expect(screen.getByLabelText("Conflicting sources")).toHaveTextContent("unclear which applies");
  });

  it("shows a distinct abstain state", () => {
    const msg: ChatMessage = {
      id: "b", role: "assistant", status: "insufficient_evidence",
      content: "I couldn't find enough information in your documents to answer that.",
      citations: [], conflicts: [],
    };
    render(<MessageView message={msg} onCite={() => {}} />);
    expect(screen.getByText("Not enough evidence")).toBeInTheDocument();
    expect(screen.queryByLabelText("Sources")).not.toBeInTheDocument();
  });

  it("renders document-derived text as text, never HTML", () => {
    const msg = { ...answered, content: "<img src=x onerror=alert(1)> 10 days [1]." };
    const { container } = render(<MessageView message={msg} onCite={() => {}} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent("<img src=x onerror=alert(1)>");
  });
});
