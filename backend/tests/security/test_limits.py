"""Rate limits and per-tenant quotas, enforced in Postgres, plus /usage."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import ask
from tests.docs_helpers import upload
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice, amy, nina = USERS["alice"], USERS["amy"], USERS["nina"]


@pytest.fixture
def limited(ingestion_settings, vector_index):
    settings = ingestion_settings.model_copy(
        update={
            "rate_limit_chat": 2,
            "rate_limit_upload": 100,
            "quota_free_documents": 2,
            "quota_free_storage_mb": 1,
            "quota_free_questions_per_day": 4,
        }
    )
    with TestClient(create_app(settings)) as c:
        yield c


def test_chat_rate_limit_per_user_and_org(limited):
    for _ in range(2):
        assert ask(limited, alice, ACME_ID, "Hello!").status_code == 200
    blocked = ask(limited, alice, ACME_ID, "Hello!")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1
    # Other users and other tenants have their own buckets.
    assert ask(limited, amy, ACME_ID, "Hello!").status_code == 200
    assert ask(limited, nina, NOVA_ID, "Hello!").status_code == 200


def test_document_quota(limited):
    assert upload(limited, alice, ACME_ID, "a.md", b"# A\n\nAlpha.").status_code == 202
    assert upload(limited, alice, ACME_ID, "b.md", b"# B\n\nBravo.").status_code == 202
    third = upload(limited, alice, ACME_ID, "c.md", b"# C\n\nCharlie.")
    assert third.status_code == 429
    err = third.json()["error"]
    assert (err["code"], err["quota"], err["limit"], err["used"]) == (
        "quota_exceeded",
        "documents",
        2,
        2,
    )
    # Quotas are per tenant.
    assert upload(limited, nina, NOVA_ID, "n.md", b"# N\n\nNova.").status_code == 202


def test_storage_quota(limited):
    big = b"# Big\n\n" + b"word " * 220_000  # ~1.1 MB > 1 MB quota
    resp = upload(limited, alice, ACME_ID, "big.md", big)
    assert resp.status_code in (413, 429)
    if resp.status_code == 429:
        assert resp.json()["error"]["quota"] == "storage"


def test_questions_per_day_quota_and_enterprise_unlimited(limited, seeded):
    from tests.helpers import mint_token  # noqa: F401

    counted = 0
    with psycopg.connect(seeded["admin"]) as conn:
        for _ in range(4):
            conn.execute(
                "INSERT INTO usage_events (organization_id, user_id, kind, model)"
                " VALUES (%s, %s, 'chat', 'x')",
                (ACME_ID, alice.id),
            )
            counted += 1
    resp = ask(limited, amy, ACME_ID, "Hello!")
    assert resp.status_code == 429 and resp.json()["error"]["quota"] == "questions per day"
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute("UPDATE organizations SET plan = 'enterprise' WHERE id = %s", (ACME_ID,))
    assert ask(limited, amy, ACME_ID, "Hello!").status_code == 200


def test_usage_endpoint(docs_api, seeded):
    ask(docs_api, amy, ACME_ID, "Hello!")
    ask(docs_api, alice, ACME_ID, "Hello!")
    mine = docs_api.get(f"/v1/organizations/{ACME_ID}/usage", headers=auth_header(amy)).json()
    assert mine["me"]["questions"] == 1
    assert mine["organization"] is None and mine["quota"] is None  # members see only their own
    owner = docs_api.get(f"/v1/organizations/{ACME_ID}/usage", headers=auth_header(alice)).json()
    assert owner["organization"]["questions"] == 2
    assert owner["quota"]["plan"] == "free"
    assert owner["quota"]["questions_per_day"]["used"] == 2
    nova = docs_api.get(f"/v1/organizations/{ACME_ID}/usage", headers=auth_header(nina))
    assert nova.status_code == 404
