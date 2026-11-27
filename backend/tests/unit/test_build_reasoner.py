from app.agents.tools.reasoner import HeuristicReasoner, LLMReasoner
from app.config import Settings
from app.services.chat import build_reasoner
from app.services.llm import ExtractiveLLM


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_reasoner_choice():
    llm = ExtractiveLLM()
    assert type(build_reasoner(settings(llm_provider="openai"), llm)) is LLMReasoner
    assert type(build_reasoner(settings(llm_provider="extractive"), llm)) is HeuristicReasoner
    heuristic = settings(llm_provider="openai", agent_reasoner="heuristic")
    assert type(build_reasoner(heuristic, llm)) is HeuristicReasoner
    forced = settings(llm_provider="extractive", agent_reasoner="llm")
    assert type(build_reasoner(forced, llm)) is LLMReasoner
