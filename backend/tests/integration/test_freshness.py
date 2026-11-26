"""Ingestion status (queued/running/failed + retry) and version freshness on
citations and source previews."""

import pytest

from app.tenants.seed import ACME_ID, USERS
from tests.chat_helpers import ask
from tests.docs_helpers import docs_url, drain, upload
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice = USERS["alice"]

V1 = b"# Meal policy\n\nEffective date: 2025-01-01\n\nMeals are reimbursed up to 40 USD per day."
V2 = b"# Meal policy\n\nEffective date: 2026-01-01\n\nMeals are reimbursed up to 60 USD per day."


def get_doc(api, doc_id):
    return api.get(docs_url(ACME_ID, doc_id), headers=auth_header(alice)).json()


def test_job_status_from_queued_to_failed_to_retried(docs_api, worker):
    class Broken:
        dimensions = 64

        def embed(self, texts):
            raise RuntimeError("down")

    real = worker.embedder
    worker.embedder = Broken()
    body = upload(docs_api, alice, ACME_ID, "m.md", V1).json()
    doc_id = body["document"]["id"]
    assert get_doc(docs_api, doc_id)["job_status"] == "queued"
    listed = docs_api.get(docs_url(ACME_ID), headers=auth_header(alice)).json()
    assert listed[0]["job_status"] == "queued"

    drain(worker)
    doc = get_doc(docs_api, doc_id)
    assert doc["status"] == "failed" and doc["job_status"] == "failed"

    # Retry = reindex the failed version once the provider is back.
    worker.embedder = real
    retry = docs_api.post(docs_url(ACME_ID, doc_id, "reindex"), headers=auth_header(alice))
    assert retry.status_code == 202, retry.text
    assert get_doc(docs_api, doc_id)["job_status"] == "queued"
    drain(worker)
    doc = get_doc(docs_api, doc_id)
    assert doc["status"] == "ready" and doc["job_status"] == "succeeded"
    assert doc["current_version"]["status"] == "published"


def test_citations_and_previews_show_when_a_version_is_superseded(docs_api, worker):
    doc_id = upload(docs_api, alice, ACME_ID, "meal.md", V1).json()["document"]["id"]
    drain(worker)
    q = "How much are meals reimbursed per day?"
    first = ask(docs_api, alice, ACME_ID, q).json()
    assert first["citations"] and all(c["is_current"] for c in first["citations"])
    cite = first["citations"][0]

    # A new version is published: the old citation now points at an older version.
    v2 = docs_api.post(
        docs_url(ACME_ID, doc_id, "versions"),
        files={"file": ("meal.md", V2)},
        headers=auth_header(alice),
    )
    assert v2.status_code == 202
    drain(worker)
    conv = docs_api.get(
        f"/v1/organizations/{ACME_ID}/conversations/{first['conversation_id']}",
        headers=auth_header(alice),
    ).json()
    old = conv["messages"][1]["citations"][0]
    assert old["is_current"] is False and old["version"] == 1

    preview = docs_api.get(
        docs_url(ACME_ID, doc_id, "chunks", cite["chunk_id"]), headers=auth_header(alice)
    ).json()
    assert preview["is_current"] is False
    assert preview["version"] == 1 and preview["current_version"] == 2
    assert preview["current_effective_date"] == "2026-01-01"

    fresh = ask(docs_api, alice, ACME_ID, q).json()
    assert "60 USD" in fresh["answer"]
    assert all(c["is_current"] for c in fresh["citations"])
