"""Citation verification: every factual sentence must cite a valid source,
and its figures and most of its topic terms must appear in what it cites."""

import re
from dataclasses import dataclass, field

from app.agents.tools.conflicts import facts
from app.agents.tools.text import salient_terms, term_set
from app.services.answering import is_insufficient

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|(?<=\])\s+(?=[A-Z])")
_CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass
class Verification:
    ok: bool
    problems: list[str] = field(default_factory=list)
    supported: list[str] = field(default_factory=list)


def _cited(sentence: str) -> list[int]:
    return [int(n) for g in _CITE.findall(sentence) for n in g.split(",")]


def verify(answer: str, sources: list[str], *, min_term_support: float = 0.5) -> Verification:
    if is_insufficient(answer):
        return Verification(ok=True)
    problems, supported = [], []
    for sentence in (s.strip() for s in _SENT.split(answer.strip())):
        if not sentence:
            continue
        plain = _CITE.sub("", sentence)
        terms = salient_terms(plain)
        figures = facts(plain)
        if not terms and not figures:
            supported.append(sentence)  # connective text, nothing to support
            continue
        cited = _cited(sentence)
        if not cited:
            problems.append(f"uncited claim: {plain.strip()[:120]!r}")
            continue
        if any(n < 1 or n > len(sources) for n in cited):
            problems.append(f"citation to a non-existent source in: {plain.strip()[:120]!r}")
            continue
        text = " ".join(sources[n - 1] for n in cited)
        missing_figures = figures - facts(text)
        support = len(terms & term_set(text)) / len(terms) if terms else 1.0
        if missing_figures:
            problems.append(
                f"figure(s) {sorted(' '.join(f) for f in missing_figures)} not in cited source"
            )
        elif support < min_term_support:
            problems.append(f"claim not supported by cited source: {plain.strip()[:120]!r}")
        else:
            supported.append(sentence)
    if not supported and not problems:
        problems.append("empty answer")
    return Verification(ok=not problems, problems=problems, supported=supported)
