from pathlib import Path

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def test_env_example_loads(monkeypatch):
    """Every documented variable parses, including the empty optional ones."""
    for line in ENV_EXAMPLE.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)
    assert settings.llm_input_price_per_1m is None
    assert settings.qdrant_api_key is None
    assert settings.supabase_jwks_url is None
    assert settings.embedding_provider == "hash" and settings.llm_provider == "extractive"
