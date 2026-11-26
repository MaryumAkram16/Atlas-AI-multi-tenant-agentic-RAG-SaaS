from app.services.explain import abstain_reason, build_explanation


def test_abstain_reasons():
    base = {"intent": "knowledge", "status": "insufficient_evidence"}
    assert abstain_reason({**base, "status": "answered"}) is None
    assert abstain_reason({"intent": "greeting", "status": "direct"}) is None
    assert abstain_reason({**base, "halt": "timeout", "status": "error"}) == "limit"
    assert (
        abstain_reason({**base, "evidence_status": "none"}, has_documents=False) == "no_documents"
    )
    assert abstain_reason({**base, "evidence_status": "none", "attempts": 2}) == "no_evidence"
    assert abstain_reason({**base, "evidence_status": "weak", "attempts": 3}) == "weak_evidence"
    unverified = {"abstained": True, "problems": ["uncited claim: 'x'"]}
    assert (
        abstain_reason({**base, "evidence_status": "sufficient", "verification": unverified})
        == "unverified"
    )
    assert abstain_reason({**base, "evidence_status": "sufficient"}) == "model_declined"


def test_verification_keeps_kinds_not_claim_text():
    state = {
        "intent": "knowledge",
        "status": "answered",
        "verification": {
            "ok": False,
            "partial": True,
            "problems": ["uncited claim: 'secret text'", "empty answer"],
        },
    }
    v = build_explanation(state, [])["verification"]
    assert v == {
        "checked": True,
        "ok": False,
        "partial": True,
        "problem_count": 2,
        "problem_kinds": ["empty answer", "uncited claim"],
    }
