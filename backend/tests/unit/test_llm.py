import json

import httpx
import pytest

from app.services.llm import ExtractiveLLM, OpenAIChatLLM, TextDelta, Usage, usage_from


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
        assert "reasoning_effort" not in payload  # not sent unless configured
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


@pytest.mark.asyncio
async def test_reasoning_effort_is_sent_when_configured():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    llm = OpenAIChatLLM(
        api_key="k",
        model="gemini-test",
        max_tokens=100,
        reasoning_effort="low",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await collect(llm.stream([{"role": "user", "content": "q"}]))
    assert seen["reasoning_effort"] == "low"


def test_thinking_tokens_count_as_output():
    # Gemini: thinking appears only in total_tokens (13 visible, 150 total).
    gemini = {"prompt_tokens": 3, "completion_tokens": 10, "total_tokens": 150}
    assert usage_from("m", gemini) == Usage("m", prompt_tokens=3, completion_tokens=147)
    # OpenAI o-series: reasoning tokens are part of completion_tokens already.
    openai = {
        "prompt_tokens": 5,
        "completion_tokens": 40,
        "total_tokens": 45,
        "completion_tokens_details": {"reasoning_tokens": 30},
    }
    assert usage_from("m", openai) == Usage("m", prompt_tokens=5, completion_tokens=40)
    assert usage_from("m", {"prompt_tokens": 2, "completion_tokens": 1}).completion_tokens == 1


@pytest.mark.asyncio
async def test_busy_provider_is_retried_before_streaming():
    calls = {"n": 0}
    ok = 'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\ndata: [DONE]\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "high demand"})
        return httpx.Response(200, content=ok.encode())

    llm = OpenAIChatLLM(
        api_key="k",
        model="m",
        max_tokens=10,
        retry_base_delay=0,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    text, _ = await collect(llm.stream([{"role": "user", "content": "q"}]))
    assert text == "Hi" and calls["n"] == 3


@pytest.mark.asyncio
async def test_retries_are_bounded_and_other_errors_fail_fast():
    for status, expected_calls in ((503, 4), (400, 1)):
        calls = {"n": 0}

        def handler(request: httpx.Request, status=status, calls=calls) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(status)

        llm = OpenAIChatLLM(
            api_key="k",
            model="m",
            max_tokens=10,
            retry_base_delay=0,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(RuntimeError, match=str(status)):
            await collect(llm.stream([{"role": "user", "content": "q"}]))
        assert calls["n"] == expected_calls
