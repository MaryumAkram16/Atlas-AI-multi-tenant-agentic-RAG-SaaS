"""Documents: cross-tenant isolation, document ACLs and role limits.
Exercised via the API and directly as the restricted DB roles."""

import json

import psycopg
import pytest
from psycopg.rows import dict_row

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.docs_helpers import docs_url, drain, get_job, upload
from tests.files import sample
from tests.helpers import auth_header, restricted_session

pytestmark = pytest.mark.db

alice, aaron, amy, avery = USERS["alice"], USERS["aaron"], USERS["amy"], USERS["avery"]
nina, noah = USERS["nina"], USERS["noah"]


@pytest.fixture
def acme_doc(docs_api, worker):
    body = upload(
        docs_api, alice, ACME_ID, "refund-policy-2026.md", sample("acme/refund-policy-2026.md")
    ).json()
    drain(worker)
    return body


# ---------- cross-tenant via API ----------


@pytest.mark.parametrize("user", [nina, noah])
def test_nova_cannot_list_or_read_acme_documents(docs_api, acme_doc, user):
    doc_id = acme_doc["document"]["id"]
    h = auth_header(user)
    assert docs_api.get(docs_url(ACME_ID), headers=h).status_code == 404
    assert docs_api.get(docs_url(ACME_ID, doc_id), headers=h).status_code == 404
    # Tampering: own org in the URL, Acme document ID.
    assert docs_api.get(docs_url(NOVA_ID, doc_id), headers=h).status_code == 404
    assert docs_api.get(docs_url(NOVA_ID), headers=h).json() == []
    url = docs_url(NOVA_ID, doc_id, "versions", acme_doc["version"]["id"], "download-url")
    assert docs_api.get(url, headers=h).status_code == 404
    assert get_job(docs_api, user, ACME_ID, acme_doc["job"]["id"]).status_code == 404
    assert get_job(docs_api, user, NOVA_ID, acme_doc["job"]["id"]).status_code == 404


def test_nova_cannot_delete_or_modify_acme_documents(docs_api, acme_doc, worker, vector_index):
    doc_id = acme_doc["document"]["id"]
    h = auth_header(nina)
    assert docs_api.delete(docs_url(ACME_ID, doc_id), headers=h).status_code == 404
    assert docs_api.delete(docs_url(NOVA_ID, doc_id), headers=h).status_code == 404
    assert docs_api.post(docs_url(NOVA_ID, doc_id, "reindex"), headers=h).status_code == 404
    v = docs_api.post(
        docs_url(NOVA_ID, doc_id, "versions"), files={"file": ("x.md", b"# X\n\nx")}, headers=h
    )
    assert v.status_code == 404
    assert drain(worker) == 0  # nothing was queued
    doc = docs_api.get(docs_url(ACME_ID, doc_id), headers=auth_header(alice)).json()
    assert doc["status"] == "ready"
    assert vector_index.count(organization_id=ACME_ID, document_id=doc_id) > 0


def test_nova_upload_lands_in_nova_only(docs_api, acme_doc):
    resp = upload(docs_api, nina, NOVA_ID, "n.md", b"# Nova\n\nNova only.")
    assert resp.status_code == 202
    assert resp.json()["document"]["organization_id"] == str(NOVA_ID)
    acme_ids = {d["id"] for d in docs_api.get(docs_url(ACME_ID), headers=auth_header(alice)).json()}
    assert resp.json()["document"]["id"] not in acme_ids


# ---------- roles and document ACLs ----------


def test_viewer_can_read_but_not_upload_or_delete(docs_api, acme_doc):
    h = auth_header(avery)
    doc_id = acme_doc["document"]["id"]
    assert docs_api.get(docs_url(ACME_ID, doc_id), headers=h).status_code == 200
    assert upload(docs_api, avery, ACME_ID, "v.md", b"# V\n\nviewer").status_code == 403
    assert docs_api.delete(docs_url(ACME_ID, doc_id), headers=h).status_code == 403


def test_member_cannot_delete_someone_elses_document(docs_api, acme_doc):
    resp = docs_api.delete(docs_url(ACME_ID, acme_doc["document"]["id"]), headers=auth_header(amy))
    assert resp.status_code == 403


def test_admin_can_delete_org_document(docs_api, acme_doc):
    resp = docs_api.delete(
        docs_url(ACME_ID, acme_doc["document"]["id"]), headers=auth_header(aaron)
    )
    assert resp.status_code == 202


def test_restricted_document_hidden_even_from_owner_and_admin(docs_api, worker):
    body = upload(
        docs_api, amy, ACME_ID, "salaries.md", b"# Salaries\n\nSecret.", visibility="restricted"
    )
    assert body.status_code == 202
    doc_id = body.json()["document"]["id"]
    drain(worker)
    for user in (alice, aaron, avery):
        h = auth_header(user)
        assert doc_id not in {d["id"] for d in docs_api.get(docs_url(ACME_ID), headers=h).json()}
        assert docs_api.get(docs_url(ACME_ID, doc_id), headers=h).status_code == 404
        assert docs_api.delete(docs_url(ACME_ID, doc_id), headers=h).status_code == 404
    assert docs_api.get(docs_url(ACME_ID, doc_id), headers=auth_header(amy)).status_code == 200


def test_signed_download_url_only_after_authorization(docs_api, acme_doc):
    doc_id, version_id = acme_doc["document"]["id"], acme_doc["version"]["id"]
    url = docs_url(ACME_ID, doc_id, "versions", version_id, "download-url")
    resp = docs_api.get(url, headers=auth_header(avery))
    assert resp.status_code == 200
    signed = resp.json()["url"]
    assert resp.json()["expires_in"] <= 300
    path = signed.split("://", 1)[-1].split("/", 1)[1]
    file_resp = docs_api.get("/" + path)
    assert file_resp.status_code == 200
    assert file_resp.content == sample("acme/refund-policy-2026.md")
    tampered = "/" + path.replace("signature=", "signature=0")
    assert docs_api.get(tampered).status_code == 403


# ---------- direct DB as restricted roles ----------


def test_nova_db_session_sees_no_acme_rows(seeded, acme_doc):
    with restricted_session(seeded["api"], nina) as conn:
        for table in ["documents", "document_versions", "document_chunks", "ingestion_jobs"]:
            rows = conn.execute(f"SELECT organization_id FROM {table}").fetchall()
            assert all(r["organization_id"] == NOVA_ID for r in rows), table
        assert (
            conn.execute(
                "SELECT app_private.mark_document_deleting(%s)", (acme_doc["document"]["id"],)
            ).fetchone()["mark_document_deleting"]
            is False
        )


def test_users_cannot_write_chunks_or_publish_versions(seeded, acme_doc):
    with restricted_session(seeded["api"], alice) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM document_chunks")
    with restricted_session(seeded["api"], alice) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE document_versions SET status = 'published'")
    with restricted_session(seeded["api"], alice) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE ingestion_jobs SET status = 'succeeded'")


def test_cannot_insert_document_into_another_org(seeded):
    with restricted_session(seeded["api"], nina) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO documents (organization_id, owner_id, title) VALUES (%s, %s, 'x')",
                (ACME_ID, nina.id),
            )


def worker_session(conninfo, org_id):
    conn = psycopg.connect(conninfo, row_factory=dict_row)
    conn.execute("BEGIN")
    if org_id is not None:
        conn.execute("SELECT set_config('app.organization_id', %s, true)", (str(org_id),))
    return conn


@pytest.mark.parametrize("scope", [NOVA_ID, None])
def test_worker_role_is_pinned_to_the_job_tenant(seeded, acme_doc, scope):
    conn = worker_session(seeded["worker"], scope)
    try:
        for table in ["documents", "document_versions", "document_chunks", "ingestion_jobs"]:
            assert (
                conn.execute(
                    f"SELECT 1 FROM {table} WHERE organization_id = %s", (ACME_ID,)
                ).fetchall()
                == []
            )
        assert conn.execute("DELETE FROM document_chunks").rowcount == 0
        assert conn.execute("UPDATE documents SET status = 'failed'").rowcount == 0
    finally:
        conn.rollback()
        conn.close()
    with psycopg.connect(seeded["worker"], autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM organization_members")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SET ROLE authenticated")


def test_worker_cannot_delete_documents_not_marked_for_deletion(seeded, acme_doc):
    conn = worker_session(seeded["worker"], ACME_ID)
    try:
        assert (
            conn.execute(
                "DELETE FROM documents WHERE id = %s", (acme_doc["document"]["id"],)
            ).rowcount
            == 0
        )
    finally:
        conn.rollback()
        conn.close()


def test_claims_cannot_be_used_by_worker_role(seeded, acme_doc):
    """Setting user claims on the worker connection grants nothing."""
    conn = worker_session(seeded["worker"], None)
    try:
        conn.execute(
            "SELECT set_config('request.jwt.claims', %s, true)",
            (json.dumps({"sub": str(alice.id), "role": "authenticated"}),),
        )
        assert conn.execute("SELECT * FROM documents").fetchall() == []
    finally:
        conn.rollback()
        conn.close()


def test_restricted_document_rows_hidden_in_every_table(docs_api, worker, seeded):
    """Chunks, versions and jobs of a restricted document are as hidden as the
    document itself (they are guarded by document_access, not the documents policy)."""
    doc_id = upload(
        docs_api,
        amy,
        ACME_ID,
        "salaries.md",
        b"# Salaries\n\nSecret numbers.",
        visibility="restricted",
    ).json()["document"]["id"]
    drain(worker)
    for user in (alice, aaron, avery):
        with restricted_session(seeded["api"], user) as conn:
            for table in ["documents", "document_versions", "document_chunks", "ingestion_jobs"]:
                column = "id" if table == "documents" else "document_id"
                rows = conn.execute(
                    f"SELECT 1 FROM {table} WHERE {column} = %s", (doc_id,)
                ).fetchall()
                assert rows == [], f"{user.email} sees {table}"
            assert (
                conn.execute("SELECT app_private.document_access(%s) AS a", (doc_id,)).fetchone()[
                    "a"
                ]
                is None
            )
    with restricted_session(seeded["api"], amy) as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM document_chunks WHERE document_id = %s", (doc_id,)
            ).fetchone()["n"]
            > 0
        )
