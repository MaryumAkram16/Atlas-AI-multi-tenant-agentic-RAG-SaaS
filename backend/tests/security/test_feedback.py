"""Answer feedback: only on your own answers; admins review questions and
ratings, never answers; other tenants see nothing."""

import psycopg
import pytest

from app.tenants.seed import ACME_ID, NOVA_ID, USERS
from tests.chat_helpers import ask, load_corpus
from tests.helpers import auth_header, restricted_session

pytestmark = pytest.mark.db

alice, aaron, amy, avery = USERS["alice"], USERS["aaron"], USERS["amy"], USERS["avery"]
nina = USERS["nina"]
BASE = f"/v1/organizations/{ACME_ID}"
QUESTION = "How many days do customers have to request a refund?"


@pytest.fixture
def answer(docs_api, worker):
    load_corpus(docs_api, worker, amy, ACME_ID, ["acme/refund-policy-2026.md"])
    return ask(docs_api, avery, ACME_ID, QUESTION).json()  # a viewer can chat and rate


def url(body, org=ACME_ID):
    return (
        f"/v1/organizations/{org}/conversations/{body['conversation_id']}"
        f"/messages/{body['message_id']}/feedback"
    )


def test_rate_change_and_remove_own_answer(docs_api, answer):
    h = auth_header(avery)
    up = docs_api.put(url(answer), json={"rating": "up"}, headers=h)
    assert up.status_code == 200, up.text
    assert up.json()["rating"] == "up" and up.json()["reason"] is None
    down = docs_api.put(
        url(answer),
        json={
            "rating": "down",
            "reason": "missing_information",
            "comment": " Needs the premium rule ",
        },
        headers=h,
    )
    assert down.status_code == 200
    assert down.json()["reason"] == "missing_information"
    assert down.json()["comment"] == "Needs the premium rule"

    conv = docs_api.get(f"{BASE}/conversations/{answer['conversation_id']}", headers=h).json()
    assert conv["messages"][1]["feedback"]["rating"] == "down"
    assert conv["messages"][0]["feedback"] is None

    assert docs_api.delete(url(answer), headers=h).status_code == 204
    assert docs_api.delete(url(answer), headers=h).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"rating": "sideways"},
        {"rating": "up", "reason": "incorrect"},
        {"rating": "down", "reason": "rude"},
        {"rating": "down", "comment": "x" * 1001},
    ],
)
def test_invalid_feedback(docs_api, answer, body):
    assert docs_api.put(url(answer), json=body, headers=auth_header(avery)).status_code == 422


def test_cannot_rate_someone_elses_answer(docs_api, answer):
    for user in (alice, aaron, amy):
        resp = docs_api.put(url(answer), json={"rating": "down"}, headers=auth_header(user))
        assert resp.status_code == 404
    h = auth_header(nina)
    assert docs_api.put(url(answer), json={"rating": "up"}, headers=h).status_code == 404
    assert docs_api.put(url(answer, NOVA_ID), json={"rating": "up"}, headers=h).status_code == 404


def test_cannot_rate_a_user_message(docs_api, answer, seeded):
    with psycopg.connect(seeded["admin"]) as conn:
        (user_msg,) = conn.execute(
            "SELECT id FROM messages WHERE conversation_id = %s AND role = 'user'",
            (answer["conversation_id"],),
        ).fetchone()
    bad = {**answer, "message_id": str(user_msg)}
    assert (
        docs_api.put(url(bad), json={"rating": "up"}, headers=auth_header(avery)).status_code == 404
    )


def test_admins_review_questions_not_answers(docs_api, answer):
    docs_api.put(
        url(answer), json={"rating": "down", "reason": "incorrect"}, headers=auth_header(avery)
    )
    resp = docs_api.get(f"{BASE}/feedback?rating=down", headers=auth_header(aaron))
    assert resp.status_code == 200
    (row,) = resp.json()
    assert row["question"] == QUESTION and row["email"] == avery.email
    assert row["answer_status"] == "answered" and row["reason"] == "incorrect"
    assert "answer" not in row and "7 days" not in str(row)
    assert docs_api.get(f"{BASE}/feedback?rating=up", headers=auth_header(aaron)).json() == []
    for user in (amy, avery):
        assert docs_api.get(f"{BASE}/feedback", headers=auth_header(user)).status_code == 403
    assert docs_api.get(f"{BASE}/feedback", headers=auth_header(nina)).status_code == 404


def test_rls_on_feedback(docs_api, answer, seeded):
    docs_api.put(url(answer), json={"rating": "down"}, headers=auth_header(avery))
    with restricted_session(seeded["api"], amy) as conn:  # member, not the author
        assert conn.execute("SELECT count(*) AS n FROM message_feedback").fetchone()["n"] == 0
        assert conn.execute("UPDATE message_feedback SET rating = 'up'").rowcount == 0
        assert conn.execute("DELETE FROM message_feedback").rowcount == 0
        # Cannot attach feedback to someone else's answer.
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "INSERT INTO message_feedback (organization_id, message_id, user_id, rating,"
                " question, answer_status) VALUES (%s, %s, %s, 'up', 'q', 'answered')",
                (ACME_ID, answer["message_id"], amy.id),
            )
    with restricted_session(seeded["api"], nina) as conn:
        assert conn.execute("SELECT count(*) AS n FROM message_feedback").fetchone()["n"] == 0
    with restricted_session(seeded["api"], alice) as conn:  # owner reviews
        assert conn.execute("SELECT count(*) AS n FROM message_feedback").fetchone()["n"] == 1
        assert conn.execute("UPDATE message_feedback SET rating = 'up'").rowcount == 0
