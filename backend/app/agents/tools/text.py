"""Small text helpers shared by the agent's deterministic nodes."""

import re

from app.retrieval.sparse import tokenize

QUESTION_WORDS = frozenset(
    "what which who whom whose when where why how many much do does did can could should would "
    "will i me my we our you your they them their get gets got tell know need want please "
    "there here any some something someone still ago long also just about help info "
    "information question explain".split()
)
# Words too generic to show that evidence is about the question's topic.
GENERIC = frozenset(
    "day days week weeks month months year years time acme company employee employees staff "
    "people person policy policies rule rules allowed allow say says said bought buy "
    # Comparison vocabulary describes the question, not its topic.
    "change changed changes compare compared comparison difference different differ versus "
    "vs previous prior older newer new current latest history historical".split()
)
_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
_SUFFIXES = ("ation", "ing", "ed", "al", "e")


def stem(term: str) -> str:
    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        term = term[:-1]
    for suffix in _SUFFIXES:
        if len(term) > len(suffix) + 3 and term.endswith(suffix):
            return term[: -len(suffix)]
    return term


def salient_terms(text: str) -> set[str]:
    """Topic terms of a question: no stopwords, question words, generic words
    or bare numbers (a user's own figures are not evidence requirements)."""
    out = set()
    for token in tokenize(text):
        if token in QUESTION_WORDS or token in GENERIC or _NUMBER.match(token):
            continue
        out.add(stem(token))
    return out


def term_set(text: str) -> set[str]:
    return {stem(t) for t in tokenize(text)}


POLICY_ID = re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b")


def policy_ids(text: str) -> list[str]:
    return list(dict.fromkeys(POLICY_ID.findall(text)))
