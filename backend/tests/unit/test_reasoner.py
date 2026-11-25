import uuid

import pytest

from app.agents.tools.reasoner import HeuristicReasoner, LLMReasoner, classify
from app.services.answering import Evidence
from app.services.llm import TextDelta, Usage


@pytest.mark.parametrize(
    "question,intent",
    [
        ("hi", "greeting"),
        ("Thanks!", "greeting"),
        ("good morning team", "greeting"),
        ("help?", "clarify"),
        ("How many days?", "clarify"),
        ("Hi, how many days of annual leave do I get?", "knowledge"),
        ("What does REF-2026-07 say?", "knowledge"),
        ("How did the leave policy change compared to 2024?", "comparison"),
        ("Is the refund window shorter than in 2024?", "comparison"),
    ],
)
def test_classify(question, intent):
    assert classify(question) == intent


def ev(content):
    return Evidence(
        uuid.uuid4(), uuid.uuid4(), "t", uuid.uuid4(), 1, None, "S", None, None, content, 1.0
    )


@pytest.mark.asyncio
async def test_assess():
    r = HeuristicReasoner()
    good = [ev("Customers may request a full refund within 7 days of purchase.")]
    assert (
        await r.assess("How many days do customers have to request a refund?", good)
    ).status == "sufficient"
    assert (
        await r.assess("How many days of bereavement leave do employees get?", good)
    ).status == "weak"
    assert (await r.assess("anything", [])).status == "none"


@pytest.mark.asyncio
async def test_rewrite_adds_keywords_and_synonyms():
    r = HeuristicReasoner()
    q = "Can I get my money back for a refund?"
    first, second = await r.rewrite(q, 1), await r.rewrite(q, 2)
    assert "refund" in first and first != q
    assert "return" in second


@pytest.mark.asyncio
async def test_decompose_splits_multi_part_questions():
    r = HeuristicReasoner()
    parts = await r.decompose(
        "What is the meal allowance? And who approves expenses above 500 USD?"
    )
    assert len(parts) == 2
    assert await r.decompose("What is the meal allowance?") == []


class ScriptedLLM:
    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    async def stream(self, messages):
        yield TextDelta(self.replies.pop(0))
        yield Usage(self.name, 10, 2)


@pytest.mark.asyncio
async def test_llm_reasoner_uses_json_and_falls_back_on_garbage():
    r = LLMReasoner(ScriptedLLM(['{"query": "refund window days"}', "not json"]))
    assert await r.rewrite("refund?", 1) == "refund window days"
    fallback = await r.rewrite("Can I get a refund?", 1)
    assert "refund" in fallback  # heuristic result
    assert len(r.usage) == 2


@pytest.mark.asyncio
async def test_llm_reasoner_cannot_mark_off_topic_evidence_sufficient():
    r = LLMReasoner(ScriptedLLM(['{"sufficient": true}']))
    off_topic = [ev("Passwords must be 14 characters.")]
    a = await r.assess("What is the stock option vesting schedule?", off_topic)
    assert a.status == "weak"  # heuristic floor; the model was not asked
    assert r.usage == []
