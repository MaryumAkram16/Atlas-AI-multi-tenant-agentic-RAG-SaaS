"""Upload -> worker -> Qdrant -> published, plus retries, duplicates,
versions, reindex and safe delete. Needs Postgres and Qdrant."""

import uuid
from pathlib import Path

import psycopg
import pytest

from app.retrieval.embeddings import HashEmbedder
from app.retrieval.sparse import bm25_query_vector
from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.docs_helpers import docs_url, drain, get_job, upload, upload_version
from tests.files import make_pdf, sample
from tests.helpers import auth_header

pytestmark = pytest.mark.db

alice, amy, nina = USERS["alice"], USERS["amy"], USERS["nina"]


def admin_one(seeded, query, params=()):
    with psycopg.connect(seeded["admin"]) as conn:
        return conn.execute(query, params).fetchone()


def admin_all(seeded, query, params=()):
    with psycopg.connect(seeded["admin"]) as conn:
        return conn.execute(query, params).fetchall()


def test_upload_to_searchable_end_to_end(docs_api, worker, vector_index, seeded):
    resp = upload(
        docs_api, alice, ACME_ID, "refund-policy-2026.md", sample("acme/refund-policy-2026.md")
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    doc_id, job_id = body["document"]["id"], body["job"]["id"]
    assert body["document"]["status"] == "processing"
    assert body["job"]["status"] == "queued"
    assert body["version"]["effective_date"] is None  # detected later by the parser

    assert drain(worker) == 1

    job = get_job(docs_api, alice, ACME_ID, job_id).json()
    assert job["status"] == "succeeded" and job["attempts"] == 1

    doc = docs_api.get(docs_url(ACME_ID, doc_id), headers=auth_header(alice)).json()
    assert doc["status"] == "ready"
    version = doc["current_version"]
    assert version["status"] == "published"
    assert version["effective_date"] == "2026-01-01"
    assert version["chunk_count"] > 0

    chunks = admin_all(
        seeded,
        "SELECT id, section, embedding_status FROM document_chunks"
        " WHERE document_version_id = %s ORDER BY chunk_index",
        (version["id"],),
    )
    assert len(chunks) == version["chunk_count"]
    assert all(c[2] == "indexed" for c in chunks)
    assert any(c[1] == "Acme Refund Policy (2026) > Eligibility" for c in chunks)

    # Searchable in Qdrant with the mandatory tenant + document filters.
    assert vector_index.count(organization_id=ACME_ID, version_id=version["id"]) == len(chunks)
    hits = vector_index.search_sparse(
        bm25_query_vector("REF-2026-07"), organization_id=ACME_ID, document_ids=[doc_id], limit=5
    )
    assert hits and all(h.payload["organization_id"] == str(ACME_ID) for h in hits)
    assert {str(h.id) for h in hits} <= {str(c[0]) for c in chunks}
    dense = HashEmbedder(64).embed(["refund within 7 days"])[0]
    assert vector_index.search_dense(dense, organization_id=ACME_ID, document_ids=[doc_id], limit=3)

    # The same query scoped to Nova finds nothing.
    assert not vector_index.search_sparse(
        bm25_query_vector("REF-2026-07"), organization_id=NOVA_ID, document_ids=[doc_id], limit=5
    )


def test_pdf_chunks_keep_page_numbers(docs_api, worker, seeded):
    pdf = make_pdf(
        [["1. Eligibility", "Refunds within 14 days."], ["2. Exclusions", "Gift cards excluded."]]
    )
    doc_id = upload(docs_api, alice, ACME_ID, "policy.pdf", pdf).json()["document"]["id"]
    drain(worker)
    rows = admin_all(
        seeded,
        "SELECT section, page_start, page_end FROM document_chunks WHERE document_id = %s"
        " ORDER BY chunk_index",
        (doc_id,),
    )
    assert ("2. Exclusions", 2, 2) in rows


def test_storage_path_is_tenant_scoped(docs_api, seeded, ingestion_settings):
    body = upload(docs_api, alice, ACME_ID, "a.md", b"# A\n\nAlpha.").json()
    path = admin_one(
        seeded, "SELECT storage_path FROM document_versions WHERE id = %s", (body["version"]["id"],)
    )[0]
    assert path.startswith(f"{ACME_ID}/{body['document']['id']}/{body['version']['id']}/")
    assert (Path(ingestion_settings.local_storage_path) / path).read_bytes() == b"# A\n\nAlpha."


def test_duplicate_upload_is_detected(docs_api, worker):
    data = sample("acme/refund-policy-2024.md")
    first = upload(docs_api, alice, ACME_ID, "refund-2024.md", data).json()["document"]["id"]
    dup = upload(docs_api, alice, ACME_ID, "copy.md", data)
    assert dup.status_code == 409
    assert dup.json()["detail"]["existing_document_id"] == first
    # Same bytes as a new version of the same document is also a duplicate.
    again = upload_version(docs_api, alice, ACME_ID, first, "refund-2024.md", data)
    assert again.status_code == 409


def test_duplicate_check_does_not_leak_hidden_documents(docs_api):
    data = b"# Salaries\n\nConfidential."
    assert upload(docs_api, amy, ACME_ID, "s.md", data, visibility="restricted").status_code == 202
    # Alice can't see Amy's restricted doc, so her identical upload is allowed.
    assert upload(docs_api, alice, ACME_ID, "s.md", data).status_code == 202


def test_idempotency_key_returns_the_same_document(docs_api):
    data = b"# Idem\n\nOnce."
    h = {"Idempotency-Key": "upload-123"}
    first = upload(docs_api, alice, ACME_ID, "i.md", data, headers=h)
    second = upload(docs_api, alice, ACME_ID, "i.md", data, headers=h)
    assert first.status_code == 202 and second.status_code == 200
    assert first.json()["document"]["id"] == second.json()["document"]["id"]
    assert first.json()["job"]["id"] == second.json()["job"]["id"]


def test_new_version_supersedes_and_republishes(docs_api, worker, seeded):
    doc_id = upload(
        docs_api,
        alice,
        ACME_ID,
        "refund.md",
        sample("acme/refund-policy-2024.md"),
        effective_date="2024-01-01",
    ).json()["document"]["id"]
    drain(worker)
    resp = upload_version(
        docs_api, alice, ACME_ID, doc_id, "refund.md", sample("acme/refund-policy-2026.md")
    )
    assert resp.status_code == 202
    assert resp.json()["version"]["version"] == 2
    drain(worker)

    doc = docs_api.get(docs_url(ACME_ID, doc_id), headers=auth_header(alice)).json()
    assert doc["current_version"]["version"] == 2
    assert [(v["version"], v["status"]) for v in doc["versions"]] == [
        (2, "published"),
        (1, "superseded"),
    ]


def test_failed_job_retries_then_fails_cleanly(docs_api, worker, vector_index, seeded):
    calls = {"n": 0}

    class BrokenEmbedder:
        dimensions = 64

        def embed(self, texts):
            calls["n"] += 1
            raise RuntimeError("embedding provider unavailable: secret sk-live-123")

    worker.embedder = BrokenEmbedder()
    body = upload(docs_api, alice, ACME_ID, "f.md", b"# F\n\nWill fail.").json()
    doc_id, job_id = body["document"]["id"], body["job"]["id"]

    # Attempt 1 fails and is requeued with backoff (base 0 in tests).
    assert worker.run_once()
    job = get_job(docs_api, alice, ACME_ID, job_id).json()
    assert (job["status"], job["attempts"]) == ("queued", 1)

    drain(worker)
    job = get_job(docs_api, alice, ACME_ID, job_id).json()
    assert job["status"] == "failed"
    assert job["attempts"] == job["max_attempts"] == calls["n"]
    assert "RuntimeError" in job["last_error"]
    assert "sk-live" not in job["last_error"]  # error text is sanitized

    doc = docs_api.get(docs_url(ACME_ID, doc_id), headers=auth_header(alice)).json()
    assert doc["status"] == "failed"
    assert doc["current_version"] is None
    assert doc["versions"][0]["status"] == "failed"
    assert (
        admin_one(seeded, "SELECT count(*) FROM document_chunks WHERE document_id = %s", (doc_id,))[
            0
        ]
        == 0
    )
    assert vector_index.count(organization_id=ACME_ID, document_id=doc_id) == 0


def test_backoff_delays_the_retry(docs_api, worker, ingestion_settings, seeded):
    class Broken:
        dimensions = 64

        def embed(self, texts):
            raise RuntimeError("down")

    worker.embedder = Broken()
    worker.backoff_base = 30
    job_id = upload(docs_api, alice, ACME_ID, "b.md", b"# B\n\nBackoff.").json()["job"]["id"]
    assert worker.run_once()
    assert not worker.run_once()  # not due yet
    run_after_future = admin_one(
        seeded,
        "SELECT run_after > now() + interval '10 seconds' FROM ingestion_jobs WHERE id = %s",
        (job_id,),
    )[0]
    assert run_after_future


def test_crashed_worker_lease_is_reclaimed(docs_api, worker, seeded):
    job_id = upload(docs_api, alice, ACME_ID, "c.md", b"# C\n\nCrash.").json()["job"]["id"]
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute(
            "UPDATE ingestion_jobs SET status = 'running', attempts = 1, locked_by = 'dead',"
            " locked_at = now() - interval '1 hour' WHERE id = %s",
            (job_id,),
        )
    assert drain(worker) == 1
    job = get_job(docs_api, alice, ACME_ID, job_id).json()
    assert (job["status"], job["attempts"]) == ("succeeded", 2)


def test_reindex_is_idempotent(docs_api, worker, vector_index, seeded):
    doc_id = upload(docs_api, alice, ACME_ID, "r.md", sample("acme/refund-policy-2026.md")).json()[
        "document"
    ]["id"]
    drain(worker)
    before = admin_all(
        seeded, "SELECT id FROM document_chunks WHERE document_id = %s ORDER BY id", (doc_id,)
    )

    resp = docs_api.post(docs_url(ACME_ID, doc_id, "reindex"), headers=auth_header(alice))
    assert resp.status_code == 202
    assert (
        docs_api.post(docs_url(ACME_ID, doc_id, "reindex"), headers=auth_header(alice)).status_code
        == 409
    )
    drain(worker)

    after = admin_all(
        seeded, "SELECT id FROM document_chunks WHERE document_id = %s ORDER BY id", (doc_id,)
    )
    assert before == after  # deterministic chunk IDs
    assert vector_index.count(organization_id=ACME_ID, document_id=doc_id) == len(after)
    doc = docs_api.get(docs_url(ACME_ID, doc_id), headers=auth_header(alice)).json()
    assert doc["status"] == "ready"


def test_safe_delete_removes_vectors_storage_and_rows(
    docs_api, worker, vector_index, seeded, ingestion_settings
):
    body = upload(docs_api, alice, ACME_ID, "d.md", sample("acme/refund-policy-2026.md")).json()
    doc_id = body["document"]["id"]
    drain(worker)
    storage_dir = Path(ingestion_settings.local_storage_path) / str(ACME_ID) / doc_id
    assert storage_dir.exists()
    assert vector_index.count(organization_id=ACME_ID, document_id=doc_id) > 0

    resp = docs_api.delete(docs_url(ACME_ID, doc_id), headers=auth_header(alice))
    assert resp.status_code == 202
    delete_job = resp.json()["id"]
    listed = docs_api.get(docs_url(ACME_ID), headers=auth_header(alice)).json()
    assert [d["status"] for d in listed if d["id"] == doc_id] == ["deleting"]

    drain(worker)
    assert docs_api.get(docs_url(ACME_ID, doc_id), headers=auth_header(alice)).status_code == 404
    assert vector_index.count(organization_id=ACME_ID, document_id=doc_id) == 0
    assert not storage_dir.exists()
    assert (
        admin_one(
            seeded, "SELECT count(*) FROM document_versions WHERE document_id = %s", (doc_id,)
        )[0]
        == 0
    )
    job = get_job(docs_api, alice, ACME_ID, delete_job).json()
    assert job["status"] == "succeeded" and job["document_id"] is None


@pytest.mark.parametrize(
    "name,data,status",
    [("x.exe", b"MZ\x90", 415), ("big.txt", b"x" * (1024 * 1024 + 1), 413), ("e.txt", b"", 400)],
)
def test_upload_validation_via_api(docs_api, name, data, status):
    assert upload(docs_api, alice, ACME_ID, name, data).status_code == status


def test_unknown_job_is_404(docs_api):
    assert get_job(docs_api, alice, ACME_ID, uuid.uuid4()).status_code == 404
