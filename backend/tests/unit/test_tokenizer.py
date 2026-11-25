import os

import pytest

from app.ingestion.tokenizer import SimpleTokenizer, get_tokenizer


def test_simple_tokenizer_round_trips():
    tok = SimpleTokenizer()
    text = "Refund policy REF-2026-07: seven days."
    assert tok.decode(tok.encode(text)) == text


def test_tiktoken_cl100k():
    """Real tokenizer used for text-embedding-3-small. Needs the encoding file
    (downloaded once, baked into the Docker image); CI requires it."""
    try:
        tok = get_tokenizer("tiktoken")
        tokens = tok.encode("Refund policy REF-2026-07 allows seven days.")
    except Exception as exc:  # network blocked in some sandboxes
        if os.environ.get("ATLAS_REQUIRE_STACK"):
            raise
        pytest.skip(f"tiktoken encoding unavailable: {type(exc).__name__}")
    assert 5 < len(tokens) < 20
    assert tok.decode(tokens) == "Refund policy REF-2026-07 allows seven days."
