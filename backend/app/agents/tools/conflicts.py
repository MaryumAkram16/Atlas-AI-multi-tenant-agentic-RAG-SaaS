"""Deterministic conflict detection and version comparison.

A conflict is two or more documents in the evidence that answer the question
with different figures in the same unit (e.g. "14 days" vs "7 days"). They are
resolved, in order, by:
  1. explicit precedence stated in the documents ("Supersedes: X", "Status:
     Outdated", "overriding ... X" for scoped exceptions);
  2. effective dates (later wins), marked as inferred;
otherwise the conflict is reported as ambiguous.
"""

import re
from dataclasses import dataclass, field, replace
from datetime import date
from uuid import UUID

from app.agents.tools.text import policy_ids, term_set
from app.services.answering import Evidence

_POLICY_LINE = re.compile(r"(?:Policy|Document)\s+ID:\s*([A-Z][A-Z0-9-]+)", re.IGNORECASE)
_SUPERSEDES = re.compile(r"Supersedes:\s*([A-Z0-9 ,-]+)", re.IGNORECASE)
_OUTDATED = re.compile(r"Status:\s*Outdated", re.IGNORECASE)
_OVERRIDES = re.compile(r"overrid\w*[^.]*?\b([A-Z]{2,}(?:-[A-Z0-9]+)+)")
_FACT = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(?:business\s+|working\s+|calendar\s+)?"
    r"(days?|weeks?|months?|hours?|years?|USD|percent|%)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocMeta:
    document_id: UUID
    title: str
    version_id: UUID
    effective_date: date | None
    policy_id: str | None = None
    supersedes: tuple[str, ...] = ()
    overrides: tuple[str, ...] = ()
    outdated: bool = False


@dataclass
class ConflictDoc:
    document_id: UUID
    title: str
    policy_id: str | None
    effective_date: date | None
    values: list[str]
    status: str = "current"  # current | superseded | outdated | exception
    reason: str | None = None


@dataclass
class Conflict:
    topic: str
    documents: list[ConflictDoc]
    resolution: str = "unresolved"  # resolved | ambiguous
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "topic": self.topic,
            "resolution": self.resolution,
            "notes": self.notes,
            "documents": [
                {
                    "document_id": str(d.document_id),
                    "title": d.title,
                    "policy_id": d.policy_id,
                    "effective_date": d.effective_date.isoformat() if d.effective_date else None,
                    "values": d.values,
                    "status": d.status,
                    "reason": d.reason,
                }
                for d in self.documents
            ],
        }


def parse_meta(ev: Evidence, header: str | None, texts: list[str]) -> DocMeta:
    head = header or ""
    m = _POLICY_LINE.search(head)
    sup = _SUPERSEDES.search(head)
    overrides = {o for t in texts for o in _OVERRIDES.findall(t)}
    pid = m.group(1).upper() if m else None
    return DocMeta(
        document_id=ev.document_id,
        title=ev.document_title,
        version_id=ev.version_id,
        effective_date=ev.effective_date,
        policy_id=pid,
        supersedes=tuple(policy_ids(sup.group(1).upper())) if sup else (),
        overrides=tuple(sorted(o for o in overrides if o != pid)),
        outdated=bool(_OUTDATED.search(head)),
    )


def facts(text: str) -> set[tuple[str, str]]:
    out = set()
    for value, unit in _FACT.findall(text):
        unit = unit.lower().rstrip("s") if unit.upper() != "USD" else "usd"
        out.add((value.replace(",", ""), "%" if unit in ("percent", "%") else unit))
    return out


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def on_topic_facts(ev: Evidence, question_terms: set[str]) -> set[tuple[str, str]]:
    """Figures from sentences about the question's topic.

    A sentence counts when its section heading is about the question's topic,
    or when the sentence and heading together share at least two of the
    question's topic terms (all of them when there are fewer). One common word
    is not enough: "Customer deletion requests ... within 30 days" is not about
    a customer's refund.
    """
    if not question_terms:
        return facts(ev.content)
    needed = min(2, len(question_terms))
    heading = question_terms & term_set(ev.section or "")
    out: set[tuple[str, str]] = set()
    for sentence in _SENTENCE.split(ev.content):
        found = facts(sentence)
        if not found:
            continue
        if heading or len(question_terms & term_set(sentence)) >= needed:
            out |= found
    return out


def detect_conflicts(
    evidence: list[Evidence], metas: dict[UUID, DocMeta], question_terms: set[str]
) -> list[Conflict]:
    """Group documents whose on-topic evidence gives different values in the same unit."""
    by_doc: dict[UUID, set[tuple[str, str]]] = {}
    for ev in evidence:
        by_doc.setdefault(ev.document_id, set()).update(on_topic_facts(ev, question_terms))
    docs = [d for d, f in by_doc.items() if f]
    # Union-find over documents that disagree in some unit.
    parent = {d: d for d in docs}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    units_of: dict[frozenset, set[str]] = {}
    for i, a in enumerate(docs):
        for b in docs[i + 1 :]:
            ua = {u for _, u in by_doc[a]}
            shared = ua & {u for _, u in by_doc[b]}
            differing = {
                u
                for u in shared
                if {v for v, uu in by_doc[a] if uu == u} != {v for v, uu in by_doc[b] if uu == u}
            }
            if differing:
                parent[find(a)] = find(b)
                units_of.setdefault(frozenset((a, b)), set()).update(differing)
    groups: dict[UUID, list[UUID]] = {}
    for d in docs:
        groups.setdefault(find(d), []).append(d)

    conflicts = []
    for members in groups.values():
        if len(members) < 2:
            continue
        units = sorted({u for pair, us in units_of.items() if pair <= set(members) for u in us})
        conflicts.append(
            Conflict(
                topic=", ".join(units),
                documents=[
                    ConflictDoc(
                        document_id=d,
                        title=metas[d].title,
                        policy_id=metas[d].policy_id,
                        effective_date=metas[d].effective_date,
                        values=sorted(f"{v} {u}" for v, u in by_doc[d] if u in units),
                    )
                    for d in sorted(members, key=lambda x: metas[x].title)
                ],
            )
        )
    return conflicts


def _plural(value: str) -> str:
    """'30 day' -> '30 days' for readable notes (units are stored singular)."""
    number, _, unit = value.partition(" ")
    if unit and unit not in ("%", "usd") and number != "1" and not unit.endswith("s"):
        return f"{number} {unit}s"
    return value


def resolve(conflict: Conflict, metas: dict[UUID, DocMeta]) -> Conflict:
    docs = {d.document_id: replace(d) for d in conflict.documents}
    by_policy = {metas[d].policy_id: d for d in docs if metas[d].policy_id}
    notes: list[str] = []

    for d, cd in docs.items():
        meta = metas[d]
        if meta.outdated:
            cd.status, cd.reason = "outdated", "document is marked outdated"
            stated = f" (it states {', '.join(_plural(v) for v in cd.values)})" if cd.values else ""
            notes.append(f"{_label(meta)} is marked outdated{stated}; it is not among the sources.")
        for old in meta.supersedes:
            if old in by_policy and docs[by_policy[old]].status == "current":
                target = docs[by_policy[old]]
                target.status, target.reason = (
                    "superseded",
                    f"superseded by {_label(meta)} (explicit)",
                )
                notes.append(f"{_label(meta)} supersedes {_label(metas[by_policy[old]])}.")
        for base in meta.overrides:
            if base in by_policy:
                cd.status, cd.reason = (
                    "exception",
                    f"scoped exception to {_label(metas[by_policy[base]])}",
                )
                notes.append(
                    f"{_label(meta)} is an explicit exception to {_label(metas[by_policy[base]])} "
                    "for the cases it names; the base policy still applies otherwise."
                )

    current = [d for d in docs.values() if d.status == "current"]
    if len(current) > 1:
        dated = [d for d in current if d.effective_date]
        if len(dated) == len(current) and len({d.effective_date for d in dated}) == len(dated):
            latest = max(dated, key=lambda d: d.effective_date)
            for d in dated:
                if d is not latest:
                    d.status = "superseded"
                    d.reason = (
                        f"older effective date than {latest.title} "
                        "(inferred, no explicit precedence)"
                    )
            notes.append(
                f"No explicit precedence; {latest.title} has the latest effective date "
                f"({latest.effective_date.isoformat()})."
            )
            resolution = "resolved"
        else:
            resolution = "ambiguous"
            notes.append(
                "These documents disagree and neither precedence nor distinct effective dates "
                "settle it; report the uncertainty."
            )
    else:
        resolution = "resolved"
    return Conflict(conflict.topic, list(docs.values()), resolution, notes)


def _label(meta: DocMeta) -> str:
    when = f", effective {meta.effective_date.isoformat()}" if meta.effective_date else ""
    return f"{meta.policy_id or meta.title} ({meta.title}{when})"


def excluded_documents(conflicts: list[Conflict]) -> set[UUID]:
    """Documents to leave out of a normal (non-comparison) answer: explicitly
    superseded or outdated. Date-inferred losers stay, flagged in notes."""
    return {
        d.document_id
        for c in conflicts
        for d in c.documents
        if d.status == "outdated" or (d.status == "superseded" and "(explicit)" in (d.reason or ""))
    }
