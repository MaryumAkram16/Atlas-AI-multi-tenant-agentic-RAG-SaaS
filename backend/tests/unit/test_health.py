from app.services import readiness


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_when_all_dependencies_up(client, monkeypatch):
    async def all_up(_settings):
        return {"postgres": True, "qdrant": True}

    monkeypatch.setattr(readiness, "run_checks", all_up)
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"postgres": True, "qdrant": True}}


def test_ready_returns_503_when_a_dependency_is_down(client, monkeypatch):
    async def qdrant_down(_settings):
        return {"postgres": True, "qdrant": False}

    monkeypatch.setattr(readiness, "run_checks", qdrant_down)
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"
    assert resp.json()["checks"]["qdrant"] is False


async def test_real_checks_report_unreachable_services():
    from app.config import Settings

    settings = Settings(
        database_url="postgresql://u:p@127.0.0.1:1/db",
        qdrant_url="http://127.0.0.1:1",
        ready_check_timeout_seconds=1,
    )
    assert await readiness.run_checks(settings) == {"postgres": False, "qdrant": False}
