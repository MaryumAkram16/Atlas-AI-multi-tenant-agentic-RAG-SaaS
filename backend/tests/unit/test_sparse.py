from app.retrieval.sparse import bm25_document_vector, bm25_query_vector, tokenize


def test_tokenize_keeps_policy_ids():
    assert "ref-2026-07" in tokenize("See policy REF-2026-07, effective now.")


def test_document_vector_is_deterministic_and_sorted():
    a = bm25_document_vector("Refunds within 7 days. Refunds are fast.")
    b = bm25_document_vector("Refunds within 7 days. Refunds are fast.")
    assert a == b
    assert a.indices == sorted(a.indices)
    assert len(set(a.indices)) == len(a.indices)


def test_term_frequency_saturates():
    once = bm25_document_vector("refund policy")
    many = bm25_document_vector("refund refund refund refund policy")
    idx = bm25_query_vector("refund").indices[0]
    w_once = once.values[once.indices.index(idx)]
    w_many = many.values[many.indices.index(idx)]
    assert w_once < w_many < 2.2 * w_once  # k1=1.2 caps growth


def test_query_vector_matches_document_terms():
    doc = bm25_document_vector("Policy REF-2026-07 sets a seven day window")
    query = bm25_query_vector("REF-2026-07")
    assert set(query.indices) <= set(doc.indices)
    assert all(v == 1.0 for v in query.values)
