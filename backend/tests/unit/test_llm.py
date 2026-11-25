import json

import httpx
import pytest

from app.services.llm import ExtractiveLLM, OpenAIChatLLM, TextDelta, Usage


async def collect(stream):
    text, usage = "", None
    async for event in stream:
        if isinstance(event, TextDelta):
            text += event.text
        elif isinstance(event, Usage):
            usage = event
    return text, usage


@pytest.mark.asyncio
async def test_extractive_llm_quotes_relevant_sentences_with_citations():
    messages = [
        {"role": "system", "content": "..."},
        {
            "role": "user",
            "content": (
                '<source id="1" title="Refunds">Customers may request a full refund within '
                "7 days of purchase. Gift cards are excluded.</source>\n"
                '<source id="2" title="Leave">Employees get 25 days of leave.</source>\n'
                "Question: How many days do customers have to request a refund?"
            ),
        },
    ]
    text, usage = await collect(ExtractiveLLM().stream(messages))
    assert "7 days" in text and "[1]" in text
    assert "25 days" not in text
    assert usage == Usage(model="extractive", prompt_tokens=0, completion_tokens=0)


@pytest.mark.asyncio
async def test_extractive_llm_says_so_when_nothing_matches():
    messages = [
        {"role": "user", "content": '<source id="1" title="x">Alpha beta.</source>\nQuestion: zzz?'}
    ]
    text, _ = await collect(ExtractiveLLM().stream(messages))
    assert "couldn't find" in text.lower()


@pytest.mark.asyncio
async def test_openai_streaming_parses_deltas_and_usage():
    chunks = [
        {"choices": [{"delta": {"content": "Seven "}}]},
        {"choices": [{"delta": {"content": "days [1]."}}]},
        {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 5}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True and payload["stream_options"] == {"include_usage": True}
        assert payload["model"] == "gpt-test" and payload["temperature"] == 0
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "text/event-stream"}
        )

    llm = OpenAIChatLLM(
        api_key="sk-test",
        model="gpt-test",
        max_tokens=100,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    text, usage = await collect(llm.stream([{"role": "user", "content": "q"}]))
    assert text == "Seven days [1]."
    assert usage == Usage(model="gpt-test", prompt_tokens=120, completion_tokens=5)


@pytest.mark.asyncio
async def test_openai_error_status_raises_without_body():
    def handler(request):
        return httpx.Response(500, text="internal details with document text")

    llm = OpenAIChatLLM(
        api_key="k",
        model="m",
        max_tokens=10,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError) as exc:
        await collect(llm.stream([{"role": "user", "content": "q"}]))
    assert "500" in str(exc.value) and "document text" not in str(exc.value)
