"""Tokenizers for chunking. Production uses tiktoken's cl100k_base, the
encoding of text-embedding-3-small. `simple` is an offline approximation for
environments that cannot download the encoding (some sandboxes, unit tests)."""

import re
from functools import lru_cache
from typing import Protocol


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...
    def decode(self, tokens: list[int]) -> str: ...


class SimpleTokenizer:
    """Word-level pieces with leading whitespace attached (like BPE tokenizers
    do), so counts are in the same ballpark as tiktoken. Lossless."""

    _pattern = re.compile(r"\s*\w+|\s*[^\w\s]|\s+")

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._pieces: list[str] = []

    def encode(self, text: str) -> list[int]:
        out = []
        for piece in self._pattern.findall(text):
            if piece not in self._ids:
                self._ids[piece] = len(self._pieces)
                self._pieces.append(piece)
            out.append(self._ids[piece])
        return out

    def decode(self, tokens: list[int]) -> str:
        return "".join(self._pieces[t] for t in tokens)


class TiktokenTokenizer:
    def __init__(self, encoding: str = "cl100k_base") -> None:
        import tiktoken

        self._enc = tiktoken.get_encoding(encoding)

    def encode(self, text: str) -> list[int]:
        return self._enc.encode(text, disallowed_special=())

    def decode(self, tokens: list[int]) -> str:
        return self._enc.decode(tokens)


@lru_cache
def get_tokenizer(name: str) -> Tokenizer:
    if name == "tiktoken":
        return TiktokenTokenizer()
    if name == "simple":
        return SimpleTokenizer()
    raise ValueError(f"unknown tokenizer {name!r}")
