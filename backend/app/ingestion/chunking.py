"""Section-aware chunking: a chunk never spans two sections. Sections longer
than `max_tokens` are split with a sliding window that overlaps by `overlap`
tokens. Page numbers are tracked per token so citations stay exact."""

from dataclasses import dataclass
from itertools import groupby

from app.ingestion.parsing import Block
from app.ingestion.tokenizer import Tokenizer


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str
    token_count: int
    page_start: int | None
    page_end: int | None
    section: str | None


def chunk_blocks(
    blocks: list[Block], tokenizer: Tokenizer, *, max_tokens: int, overlap: int
) -> list[Chunk]:
    if not 0 <= overlap < max_tokens:
        raise ValueError("overlap must be >= 0 and smaller than max_tokens")
    chunks: list[Chunk] = []
    for headings, group in groupby(blocks, key=lambda b: b.headings):
        tokens: list[int] = []
        pages: list[int | None] = []
        for block in group:
            if not block.text.strip():
                continue
            if tokens:
                sep = tokenizer.encode("\n\n")
                tokens += sep
                pages += [block.page] * len(sep)
            piece = tokenizer.encode(block.text.strip())
            tokens += piece
            pages += [block.page] * len(piece)
        if not tokens:
            continue
        section = " > ".join(headings) or None
        step = max_tokens - overlap
        start = 0
        while True:
            window = tokens[start : start + max_tokens]
            window_pages = [p for p in pages[start : start + max_tokens] if p is not None]
            content = tokenizer.decode(window).strip()
            if content:
                chunks.append(
                    Chunk(
                        index=len(chunks),
                        content=content,
                        token_count=len(window),
                        page_start=min(window_pages) if window_pages else None,
                        page_end=max(window_pages) if window_pages else None,
                        section=section,
                    )
                )
            if start + max_tokens >= len(tokens):
                break
            start += step
    return chunks
