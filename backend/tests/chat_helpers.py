"""Helpers for chat tests."""

import json

from tests.docs_helpers import drain, upload
from tests.files import sample
from tests.helpers import auth_header


def chat_url(org_id) -> str:
    return f"/v1/organizations/{org_id}/chat"


def ask(api, user, org_id, question, **body):
    return api.post(
        chat_url(org_id), json={"question": question, **body}, headers=auth_header(user)
    )


def ask_stream(api, user, org_id, question, **body) -> list[tuple[str, dict]]:
    headers = {**auth_header(user), "Accept": "text/event-stream"}
    with api.stream(
        "POST", chat_url(org_id), json={"question": question, **body}, headers=headers
    ) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = "".join(r.iter_text())
    events = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def load_corpus(api, worker, user, org_id, names):
    ids = {}
    for name in names:
        resp = upload(api, user, org_id, name.split("/")[-1], sample(name))
        assert resp.status_code == 202, resp.text
        ids[name] = resp.json()["document"]["id"]
    drain(worker)
    return ids
