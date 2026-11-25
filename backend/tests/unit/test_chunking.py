from app.ingestion.chunking import chunk_blocks
from app.ingestion.parsing import Block
from app.ingestion.tokenizer import SimpleTokenizer

TOK = SimpleTokenizer()


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_sections_are_not_merged():
    blocks = [
        Block("Intro text here.", 1, ("Policy",)),
        Block("Seven days.", 1, ("Policy", "Eligibility")),
        Block("Gift cards.", 2, ("Policy", "Exclusions")),
    ]
    chunks = chunk_blocks(blocks, TOK, max_tokens=512, overlap=64)
    assert [c.section for c in chunks] == [
        "Policy",
        "Policy > Eligibility",
        "Policy > Exclusions",
    ]
    assert [c.index for c in chunks] == [0, 1, 2]
    assert chunks[2].page_start == chunks[2].page_end == 2


def test_long_section_uses_sliding_window_with_overlap():
    text = words(1200)
    chunks = chunk_blocks([Block(text, None, ("Big",))], TOK, max_tokens=512, overlap=64)
    assert all(c.token_count <= 512 for c in chunks)
    assert len(chunks) == 3  # windows start at 0, 448, 896
    first, second = chunks[0].content.split(), chunks[1].content.split()
    assert first[-64:] == second[:64]
    # Every word survives.
    joined = " ".join(c.content for c in chunks)
    assert all(f"w{i}" in joined.split() for i in (0, 511, 600, 1199))


def test_pages_span_blocks():
    blocks = [Block(words(300, "a"), 3, ("S",)), Block(words(300, "b"), 4, ("S",))]
    chunks = chunk_blocks(blocks, TOK, max_tokens=512, overlap=64)
    assert (chunks[0].page_start, chunks[0].page_end) == (3, 4)
    assert (chunks[-1].page_start, chunks[-1].page_end) == (4, 4)


def test_empty_blocks_produce_no_chunks():
    assert chunk_blocks([Block("   ", 1, ())], TOK, max_tokens=512, overlap=64) == []
