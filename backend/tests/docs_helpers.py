"""Helpers for document API tests."""

from tests.helpers import auth_header


def docs_url(org_id, *parts) -> str:
    return "/".join([f"/v1/organizations/{org_id}/documents", *map(str, parts)])


def upload(api, user, org_id, name, data, *, headers=None, **form):
    return api.post(
        docs_url(org_id),
        files={"file": (name, data)},
        data={k: str(v) for k, v in form.items()},
        headers={**auth_header(user), **(headers or {})},
    )


def upload_version(api, user, org_id, doc_id, name, data, **form):
    return api.post(
        docs_url(org_id, doc_id, "versions"),
        files={"file": (name, data)},
        data={k: str(v) for k, v in form.items()},
        headers=auth_header(user),
    )


def get_job(api, user, org_id, job_id):
    return api.get(f"/v1/organizations/{org_id}/jobs/{job_id}", headers=auth_header(user))


def drain(worker, limit: int = 20) -> int:
    """Run the worker until the queue is empty; return jobs processed."""
    n = 0
    while worker.run_once():
        n += 1
        assert n <= limit, "worker did not drain"
    return n
