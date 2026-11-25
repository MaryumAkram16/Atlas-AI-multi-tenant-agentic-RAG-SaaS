"""BM25 sparse vectors for Qdrant (ADR 0003).

Documents get BM25 term-frequency weights; Qdrant's IDF modifier supplies the
inverse document frequency at query time. Queries are plain term presence.
Terms are hashed to stable 32-bit indices, so no vocabulary is stored.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

K1 = 1.2
B = 0.75
AVG_DOC_TOKENS = 256  # fixed estimate; IDF comes from Qdrant

# Keeps identifiers like REF-2026-07 or v2.1 together as one term.
_TOKEN = re.compile(r"[a-z0-9]+(?:[-_./][a-z0-9]+)*")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the to was "
    "were will with this these those not no".split()
)


@dataclass(frozen=True)
class SparseVector:
    indices: list[int]
    values: list[float]


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


def _index(term: str) -> int:
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big")


def _vector(weights: dict[int, float]) -> SparseVector:
    items = sorted(weights.items())
    return SparseVector([i for i, _ in items], [v for _, v in items])


def bm25_document_vector(text: str) -> SparseVector:
    terms = tokenize(text)
    if not terms:
        return SparseVector([], [])
    norm = K1 * (1 - B + B * len(terms) / AVG_DOC_TOKENS)
    weights: dict[int, float] = {}
    for term, tf in Counter(terms).items():
        idx = _index(term)
        weights[idx] = weights.get(idx, 0.0) + tf * (K1 + 1) / (tf + norm)
    return _vector(weights)


def bm25_query_vector(text: str) -> SparseVector:
    return _vector({_index(t): 1.0 for t in set(tokenize(text))})
