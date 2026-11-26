"""The "Why this answer?" explanation, built from the final agent state.

Holds the agent's decisions and IDs/titles of documents the asker could read
when answering: search queries tried, evidence strength, versions used and
set aside, conflict resolutions, verification outcome and, when Atlas did not
answer, why. Never document text. Stored answers hide it on revocation like
the answer itself.
"""

from typing import Any

from app.services.answering import Evidence

ABSTAIN_MESSAGES = {
    "no_documents": "There are no documents you can read in this workspace yet.",
    "no_evidence": "Search found no passages from your readable documents that match the question.",
    "weak_evidence": (
        "The best passages only partly matched the question, even after rewriting the search."
    ),
    "model_declined": "The sources were related but did not contain the answer.",
    "unverified": (
        "A draft answer was written, but its claims could not be matched to the cited sources."
    ),
    "limit": "The agent hit its step or time limit before finishing.",
    "error": "Something went wrong while answering.",
}


def _verification(v: dict | None) -> dict[str, Any] | None:
    if not v:
        return None
    problems = v.get("problems") or []
    kinds = sorted({p.split(":", 1)[0] for p in problems})
    return {
        "checked": not v.get("skipped", False),
        "ok": bool(v.get("ok")),
        "partial": bool(v.get("partial")),
        "problem_count": len(problems),
        "problem_kinds": kinds,  # e.g. "uncited claim", never the claim text
    }


def abstain_reason(state: dict, has_documents: bool = True) -> str | None:
    status = state.get("status")
    if status == "answered" or state.get("intent") not in ("knowledge", "comparison", None):
        return None
    if state.get("halt"):
        return "limit"
    if status == "error":
        return "error"
    verification = state.get("verification") or {}
    if verification.get("problems") and verification.get("abstained"):
        return "unverified"
    if not has_documents:
        return "no_documents"
    evidence = state.get("evidence_status")
    if evidence == "none":
        return "no_evidence"
    if evidence == "weak":
        return "weak_evidence"
    return "model_declined"


def _sources(answer_evidence: list[Evidence], cited: set[int]) -> list[dict[str, Any]]:
    by_version: dict[str, dict[str, Any]] = {}
    for i, e in enumerate(answer_evidence, start=1):
        row = by_version.setdefault(
            str(e.version_id),
            {
                "document_id": str(e.document_id),
                "document_title": e.document_title,
                "version_id": str(e.version_id),
                "version": e.version,
                "effective_date": e.effective_date.isoformat() if e.effective_date else None,
                "passages": 0,
                "cited": False,
            },
        )
        row["passages"] += 1
        row["cited"] = row["cited"] or i in cited
    return sorted(by_version.values(), key=lambda r: (not r["cited"], r["document_title"]))


def build_explanation(state: dict, cited: list[int], has_documents: bool = True) -> dict[str, Any]:
    reason = abstain_reason(state, has_documents)
    conflicts = state.get("conflicts") if isinstance(state.get("conflicts"), list) else []
    set_aside = [
        {"title": d["title"], "status": d["status"], "reason": d.get("reason")}
        for c in conflicts
        if isinstance(c, dict)
        for d in c.get("documents", [])
        if d.get("status") in ("outdated", "superseded")
    ]
    return {
        "intent": state.get("intent"),
        "standalone_question": state.get("standalone_question"),
        "queries": state.get("query_log", []),
        "retrieval_attempts": state.get("attempts", 0),
        "candidates": len(state.get("candidates") or []),
        "authorized": state.get("authorized_count", 0),
        "evidence_status": state.get("evidence_status"),
        "evidence_reason": state.get("assessment_reason"),
        "injections_removed": state.get("injections_removed", 0),
        "sources": _sources(state.get("answer_evidence") or [], set(cited)),
        "set_aside": set_aside,
        "precedence_notes": state.get("precedence_notes") or [],
        "verification": _verification(state.get("verification")),
        "corrections": state.get("corrections", 0),
        "abstain_reason": reason,
        "abstain_message": ABSTAIN_MESSAGES.get(reason) if reason else None,
    }
