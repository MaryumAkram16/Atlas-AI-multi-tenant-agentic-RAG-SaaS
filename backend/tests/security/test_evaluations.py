"""In-product evaluations: running a dataset, roles, tenant isolation, and
results hidden from readers who cannot access their source documents."""

import psycopg
import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import load_corpus
from tests.docs_helpers import drain, upload
from tests.helpers import auth_header, restricted_session

pytestmark = pytest.mark.db

alice, aaron, amy, avery = USERS["alice"], USERS["aaron"], USERS["amy"], USERS["avery"]
nina = USERS["nina"]

BASE = f"/v1/organizations/{ACME_ID}"


@pytest.fixture
def corpus(docs_api, worker):
    return load_corpus(
        docs_api, worker, amy, ACME_ID, ["acme/refund-policy-2026.md", "acme/expenses-policy.md"]
    )


def make_dataset(api, user, corpus, name="Policies"):
    refund = corpus["acme/refund-policy-2026.md"]
    return api.post(
        f"{BASE}/evaluation-datasets",
        json={
            "name": name,
            "cases": [
                {
                    "question": "How many days do customers have to request a refund?",
                    "expected_facts": ["7 days"],
                    "expected_document_ids": [refund],
                },
                {
                    "question": "What is the stock option vesting schedule?",
                    "should_abstain": True,
                },
            ],
        },
        headers=auth_header(user),
    )


def run(api, user, dataset_id):
    return api.post(
        f"{BASE}/evaluations", json={"dataset_id": dataset_id}, headers=auth_header(user)
    )


def test_admin_creates_and_runs_a_dataset(docs_api, corpus, seeded):
    created = make_dataset(docs_api, aaron, corpus)
    assert created.status_code == 201, created.text
    dataset = created.json()
    assert dataset["case_count"] == 2 and len(dataset["cases"]) == 2

    resp = run(docs_api, aaron, dataset["id"])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "succeeded" and body["hidden_results"] == 0
    first, second = body["results"]
    assert first["fact_hit"] is True and first["evidence_hit"] is True
    assert "7 days" in first["answer"]
    assert second["abstained"] is True and second["abstention_correct"] is True
    m = body["metrics"]
    assert m["cases"] == 2 and m["fact_accuracy"] == 1.0 and m["abstention_accuracy"] == 1.0
    assert m["evidence_hit_rate"] == 1.0
    assert body["config"]["pipeline"] == "full agent"

    listed = docs_api.get(f"{BASE}/evaluations", headers=auth_header(alice)).json()
    assert [r["id"] for r in listed] == [body["id"]]
    detail = docs_api.get(f"{BASE}/evaluations/{body['id']}", headers=auth_header(alice))
    assert detail.status_code == 200 and len(detail.json()["results"]) == 2

    # Each case is metered as a question; the run is audited.
    with psycopg.connect(seeded["admin"]) as conn:
        (events,) = conn.execute(
            "SELECT count(*) FROM usage_events WHERE organization_id = %s AND message_id IS NULL",
            (ACME_ID,),
        ).fetchone()
        (audited,) = conn.execute(
            "SELECT count(*) FROM audit_logs WHERE action = 'evaluation.run_started'"
            " AND resource_id = %s",
            (body["id"],),
        ).fetchone()
    assert events == 2 and audited == 1


@pytest.mark.parametrize("user", [amy, avery])
def test_members_and_viewers_cannot_use_evaluations(docs_api, corpus, user):
    dataset = make_dataset(docs_api, alice, corpus).json()
    h = auth_header(user)
    assert make_dataset(docs_api, user, corpus, name="x").status_code == 403
    assert docs_api.get(f"{BASE}/evaluation-datasets", headers=h).status_code == 403
    assert docs_api.get(f"{BASE}/evaluation-datasets/{dataset['id']}", headers=h).status_code == 403
    assert run(docs_api, user, dataset["id"]).status_code == 403
    assert docs_api.get(f"{BASE}/evaluations", headers=h).status_code == 403


def test_members_cannot_read_evaluation_tables_directly(docs_api, corpus, seeded):
    dataset = make_dataset(docs_api, alice, corpus).json()
    run(docs_api, alice, dataset["id"])
    for user in (amy, avery, nina):
        with restricted_session(seeded["api"], user) as conn:
            for table in (
                "evaluation_datasets",
                "evaluation_cases",
                "evaluation_runs",
                "evaluation_results",
            ):
                assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
    with restricted_session(seeded["api"], alice) as conn:
        assert conn.execute("SELECT count(*) AS n FROM evaluation_results").fetchone()["n"] == 2
        # Immutable history: API roles have no DELETE privilege at all.
        for table in ("evaluation_results", "evaluation_runs"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(f"DELETE FROM {table}")
        # Results cannot be rewritten either.
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("UPDATE evaluation_results SET answer = 'x'")


def test_other_tenant_cannot_see_or_run_acme_datasets(docs_api, corpus):
    dataset = make_dataset(docs_api, alice, corpus).json()
    h = auth_header(nina)
    assert docs_api.get(f"{BASE}/evaluation-datasets", headers=h).status_code == 404
    nova = f"/v1/organizations/{NOVA_ID}"
    assert docs_api.get(f"{nova}/evaluation-datasets/{dataset['id']}", headers=h).status_code == 404
    resp = docs_api.post(f"{nova}/evaluations", json={"dataset_id": dataset["id"]}, headers=h)
    assert resp.status_code == 404
    assert docs_api.get(f"{nova}/evaluations", headers=h).json() == []


def test_expected_documents_must_be_readable(docs_api, worker, corpus):
    secret = upload(docs_api, amy, ACME_ID, "s.md", b"# S\n\nSecret.", visibility="restricted")
    drain(worker)
    resp = docs_api.post(
        f"{BASE}/evaluation-datasets",
        json={
            "name": "x",
            "cases": [
                {"question": "q?", "expected_document_ids": [secret.json()["document"]["id"]]}
            ],
        },
        headers=auth_header(alice),
    )
    assert resp.status_code == 422


def test_run_only_uses_the_runners_documents(docs_api, worker, corpus):
    # amy's restricted document is invisible to alice, so alice's run abstains.
    upload(
        docs_api,
        amy,
        ACME_ID,
        "bonus.md",
        b"# Bonus\n\nThe 2026 sales bonus pool is 4.5 percent of net revenue.",
        visibility="restricted",
    )
    drain(worker)
    ds = docs_api.post(
        f"{BASE}/evaluation-datasets",
        json={
            "name": "bonus",
            "cases": [
                {
                    "question": "How large is the 2026 sales bonus pool?",
                    "expected_facts": ["4.5 percent"],
                }
            ],
        },
        headers=auth_header(alice),
    ).json()
    result = run(docs_api, alice, ds["id"]).json()["results"][0]
    assert "4.5 percent" not in result["answer"] and result["fact_hit"] is False


def test_results_hidden_from_admins_who_cannot_read_the_sources(docs_api, worker, corpus, seeded):
    # aaron runs while the refund policy is readable, then it becomes restricted
    # to amy: alice (another admin) no longer sees the answer built from it.
    dataset = make_dataset(docs_api, aaron, corpus).json()
    body = run(docs_api, aaron, dataset["id"]).json()
    refund = corpus["acme/refund-policy-2026.md"]
    with psycopg.connect(seeded["admin"]) as conn:
        conn.execute("UPDATE documents SET visibility = 'restricted' WHERE id = %s", (refund,))
    seen = docs_api.get(f"{BASE}/evaluations/{body['id']}", headers=auth_header(alice)).json()
    assert seen["hidden_results"] == 1
    assert all("7 days" not in r["answer"] for r in seen["results"])
    assert seen["metrics"]["cases"] == 2  # aggregates stay visible
    own = docs_api.get(f"{BASE}/evaluations/{body['id']}", headers=auth_header(aaron)).json()
    assert own["hidden_results"] == 0  # the creator keeps their own results


def test_limits_and_validation(docs_api, corpus, ingestion_settings):
    h = auth_header(alice)
    empty = docs_api.post(f"{BASE}/evaluation-datasets", json={"name": "empty"}, headers=h).json()
    assert run(docs_api, alice, empty["id"]).status_code == 409
    assert make_dataset(docs_api, alice, corpus, name="dup").status_code == 201
    assert make_dataset(docs_api, alice, corpus, name="dup").status_code == 409
    bad = [
        {"question": "q?", "should_abstain": True, "expected_facts": ["x"]},
        {"question": "q?"},
        {"question": "   ", "expected_facts": ["x"]},
    ]
    for case in bad:
        resp = docs_api.post(
            f"{BASE}/evaluation-datasets", json={"name": "bad", "cases": [case]}, headers=h
        )
        assert resp.status_code == 422, case
    docs_api.app.state.settings = ingestion_settings.model_copy(update={"evaluation_max_cases": 1})
    big = make_dataset(docs_api, alice, corpus, name="big").json()
    resp = run(docs_api, alice, big["id"])
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "too_many_cases"


def test_cases_can_be_added_and_removed_and_runs_outlive_datasets(docs_api, corpus):
    h = auth_header(alice)
    ds = make_dataset(docs_api, alice, corpus).json()
    added = docs_api.post(
        f"{BASE}/evaluation-datasets/{ds['id']}/cases",
        json={"cases": [{"question": "What is the meal allowance?", "expected_facts": ["60"]}]},
        headers=h,
    )
    assert added.status_code == 201 and added.json()["case_count"] == 3
    case_id = added.json()["cases"][-1]["id"]
    url = f"{BASE}/evaluation-datasets/{ds['id']}/cases/{case_id}"
    assert docs_api.delete(url, headers=h).status_code == 204
    assert docs_api.delete(url, headers=h).status_code == 404
    body = run(docs_api, alice, ds["id"]).json()
    assert docs_api.delete(f"{BASE}/evaluation-datasets/{ds['id']}", headers=h).status_code == 204
    kept = docs_api.get(f"{BASE}/evaluations/{body['id']}", headers=h).json()
    assert kept["dataset_id"] is None and kept["dataset_name"] == "Policies"
    assert len(kept["results"]) == 2
