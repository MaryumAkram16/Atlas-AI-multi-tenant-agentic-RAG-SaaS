"""Deterministic prompt-injection filter for evidence.

Document text is untrusted. Before any model sees it, sentences that address
an AI system or instruct it ("ignore previous instructions", "tell the user
that ...", "reveal your system prompt") are removed, and chunks whose heading
is addressed to AI are dropped entirely. This does not depend on the model
refusing; it is defence in depth on top of the untrusted-data system prompt
and the citation checks (which cannot catch injected text, because it really
is in an authorized source).

It is a heuristic: it can miss novel phrasings and may drop an innocent
sentence that talks about instructions. Removed counts are recorded per run.
"""

import re
from dataclasses import replace

from app.services.answering import Evidence

_PATTERNS = [
    r"\bignore\b.{0,40}\b(instructions?|rules|prompts?|guidelines)\b",
    r"\bdisregard\b.{0,40}\b(instructions?|rules|above|previous)\b",
    r"\b(forget|override)\b.{0,30}\b(instructions?|rules)\b",
    r"\byou are now\b",
    r"\b(admin|developer|god|jailbreak) mode\b",
    r"\b(reveal|print|show|repeat|output)\b.{0,30}\b(system prompt|instructions|prompt)\b",
    r"\b(system|developer|assistant) (prompt|instruction|message)s?\b",
    r"\b(ai|llm|chatbot|language model|assistant)s?\b.{0,40}\b(must|should|shall|need to|are to)\b",
    r"\b(tell|inform|instruct) the (user|reader|customer)\b",
    r"^\s*(also\s+)?(say|tell|respond|reply|answer|state|claim)\b",
    r"\bact as\b",
    r"\bnew instructions?\b",
]
_INJECTION = re.compile("|".join(_PATTERNS), re.IGNORECASE)
_AI_HEADING = re.compile(
    r"\b(ai|llm|chatbot|assistant|language model|gpt|claude)s?\b", re.IGNORECASE
)
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def is_injection(sentence: str) -> bool:
    return bool(_INJECTION.search(sentence))


def sanitize(evidence: list[Evidence]) -> tuple[list[Evidence], int]:
    """Return evidence with injected sentences removed, and how many were removed."""
    kept: list[Evidence] = []
    removed = 0
    for ev in evidence:
        leaf = (ev.section or "").rsplit(">", 1)[-1]
        if _AI_HEADING.search(leaf):
            removed += max(1, len(_SENTENCES.split(ev.content.strip())))
            continue
        paragraphs = []
        for para in re.split(r"\n\s*\n", ev.content):
            sentences = _SENTENCES.split(" ".join(para.split()))
            clean = [s for s in sentences if s and not is_injection(s)]
            removed += len([s for s in sentences if s]) - len(clean)
            if clean:
                paragraphs.append(" ".join(clean))
        if paragraphs:
            kept.append(replace(ev, content="\n\n".join(paragraphs)))
    return kept, removed
