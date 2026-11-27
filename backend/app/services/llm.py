"""Chat model providers behind one streaming interface (replaceable)."""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings
from app.retrieval.sparse import tokenize
from app.services.answering import INSUFFICIENT_EVIDENCE_ANSWER


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Usage:
    model: str
    prompt_tokens: int
    completion_tokens: int


LLMEvent = TextDelta | Usage


class ChatLLM(Protocol):
    name: str

    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[LLMEvent]: ...


def usage_from(model: str, usage: dict) -> Usage:
    """Token usage, counting hidden "thinking" tokens as output (they are
    billed as output). Some providers report them only in total_tokens."""
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    details = usage.get("completion_tokens_details") or {}
    reasoning = int(details.get("reasoning_tokens") or 0)
    if reasoning and completion < reasoning:
        completion += reasoning  # reported separately from the visible answer
    total = int(usage.get("total_tokens") or 0)
    if total > prompt + completion:
        completion = total - prompt
    return Usage(model=model, prompt_tokens=prompt, completion_tokens=completion)


class OpenAIChatLLM:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60,
        reasoning_effort: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = model
        self._reasoning_effort = reasoning_effort
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._max_tokens = max_tokens
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[LLMEvent]:
        payload = {
            "model": self.name,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self._reasoning_effort:
            # Thinking models (e.g. Gemini, OpenAI o-series): keep thinking short;
            # the agent already plans retrieval.
            payload["reasoning_effort"] = self._reasoning_effort
        async with self._client.stream(
            "POST", self._url, json=payload, headers=self._headers
        ) as resp:
            if resp.status_code >= 400:
                # Status only: bodies can echo prompt (document) text.
                raise RuntimeError(f"chat completion failed with status {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                for choice in chunk.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield TextDelta(text)
                if usage := chunk.get("usage"):
                    yield usage_from(self.name, usage)


_SOURCE = re.compile(r'<source id="(\d+)"[^>]*>(.*?)</source>', re.DOTALL)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n\s*\n")
_QUESTION_WORDS = frozenset(
    "what which who whom whose when where why how many much do does did can could should "
    "would i my me we our you your get gets there their".split()
)


def _terms(text: str) -> set[str]:
    out = set()
    for t in tokenize(text):
        if t in _QUESTION_WORDS:
            continue
        out.add(t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t)
    return out


class ExtractiveLLM:
    """Offline, deterministic stand-in for a chat model: quotes the source
    sentences that best match the question and cites them. For local
    development and tests; it does not reason, compare versions or paraphrase."""

    name = "extractive"

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[LLMEvent]:
        user = messages[-1]["content"]
        question = user.rsplit("Question:", 1)[-1]
        q_terms = _terms(question)
        scored: list[tuple[int, int, int, str]] = []
        for source_id, body in _SOURCE.findall(user):
            # Line wraps inside a paragraph are not sentence boundaries.
            sentences = (" ".join(s.split()) for s in _SENTENCE.split(body))
            for i, sentence in enumerate(sentences):
                if sentence:
                    overlap = len(q_terms & _terms(sentence))
                    scored.append((overlap, -int(source_id), -i, sentence))
        best = max((s[0] for s in scored), default=0)
        threshold = max(1 if len(q_terms) <= 2 else 2, best - 1)
        picked = sorted((s for s in scored if s[0] >= threshold), reverse=True)[:3]
        if not picked:
            answer = INSUFFICIENT_EVIDENCE_ANSWER
        else:
            answer = " ".join(f"{sentence} [{-sid}]" for _, sid, _, sentence in picked)
        for word in re.findall(r"\S+\s*", answer):
            yield TextDelta(word)
        yield Usage(model=self.name, prompt_tokens=0, completion_tokens=0)


def build_llm(settings: Settings) -> ChatLLM:
    if settings.llm_provider == "extractive":
        return ExtractiveLLM()
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    return OpenAIChatLLM(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        base_url=settings.openai_base_url,
        timeout=settings.llm_timeout_seconds,
        reasoning_effort=settings.llm_reasoning_effort,
    )
