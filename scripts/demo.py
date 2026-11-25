"""Atlas AI demo: Acme vs Nova isolation and the refund-policy conflict answer.

Works against the local compose stack or a deployment:

    python scripts/demo.py                                   # local (http://localhost:8080)
    ATLAS_API_URL=https://atlas-api-xyz.a.run.app \\
    SUPABASE_URL=https://<ref>.supabase.co SUPABASE_ANON_KEY=... \\
    DEMO_PASSWORD=... python scripts/demo.py                 # hosted

It signs up (or signs in) two demo users, gives each a workspace, uploads the
refund policies to Acme, asks the premium-customer refund question, then checks
that Nova can neither see Acme's documents nor get Acme's answers. On hosted
Supabase with email confirmation on, confirm the two demo emails first (or use
real inboxes via DEMO_ACME_EMAIL / DEMO_NOVA_EMAIL). Exits non-zero on failure.
"""

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("ATLAS_API_URL", "http://localhost:8080").rstrip("/")
AUTH = os.environ.get("SUPABASE_URL", "http://localhost:8080").rstrip("/") + "/auth/v1"
ANON = os.environ.get("SUPABASE_ANON_KEY") or next(
    (
        line.split("=", 1)[1].strip()
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line.startswith("SUPABASE_ANON_KEY=")
    ),
    "",
)
PASSWORD = os.environ.get("DEMO_PASSWORD", "atlas-demo-password-123")
USERS = {
    "acme": os.environ.get("DEMO_ACME_EMAIL", "acme-demo@example.com"),
    "nova": os.environ.get("DEMO_NOVA_EMAIL", "nova-demo@example.com"),
}
DOCS = [
    "refund-policy-2024.md",
    "refund-policy-2026.md",
    "premium-support-policy.md",
    "customer-service-handbook-2023.md",
]
QUESTION = "A premium customer bought something 8 days ago. Can they still get a refund?"

failures: list[str] = []
http = httpx.Client(timeout=60)


def check(ok: bool, label: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    if not ok:
        failures.append(label)


def token(email: str) -> str:
    headers = {"apikey": ANON, "Content-Type": "application/json"}
    body = {"email": email, "password": PASSWORD}
    resp = http.post(f"{AUTH}/token?grant_type=password", json=body, headers=headers)
    if resp.status_code != 200:
        http.post(f"{AUTH}/signup", json=body, headers=headers)
        resp = http.post(f"{AUTH}/token?grant_type=password", json=body, headers=headers)
    if resp.status_code != 200:
        sys.exit(f"Could not sign in {email}: {resp.status_code} (confirm the email first?)")
    return resp.json()["access_token"]


def api(method: str, path: str, tok: str, **kw) -> httpx.Response:
    return http.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {tok}"}, **kw)


def workspace(tok: str, name: str, slug: str) -> str:
    for org in api("GET", "/v1/organizations", tok).json():
        if org["slug"].startswith(slug):
            return org["id"]
    for suffix in ["", f"-{int(time.time())}"]:
        resp = api("POST", "/v1/organizations", tok, json={"name": name, "slug": slug + suffix})
        if resp.status_code == 201:
            return resp.json()["id"]
    sys.exit(f"Could not create workspace {name}: {resp.text}")


def main() -> None:
    print(f"Atlas AI demo against {API}\n")
    acme, nova = token(USERS["acme"]), token(USERS["nova"])
    acme_org = workspace(acme, "Acme Demo", "acme-demo")
    nova_org = workspace(nova, "Nova Demo", "nova-demo")

    print("1. Acme uploads its refund policies")
    for name in DOCS:
        resp = api(
            "POST",
            f"/v1/organizations/{acme_org}/documents",
            acme,
            files={"file": (name, (ROOT / "sample-data/acme" / name).read_bytes())},
        )
        state = {202: "uploaded", 409: "already there"}.get(resp.status_code, resp.text[:120])
        print(f"   {name}: {state}")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        docs = api("GET", f"/v1/organizations/{acme_org}/documents", acme).json()
        if docs and all(d["status"] == "ready" for d in docs):
            break
        time.sleep(3)
    docs = api("GET", f"/v1/organizations/{acme_org}/documents", acme).json()
    check(len(docs) >= 4 and all(d["status"] == "ready" for d in docs), "Acme documents indexed")

    print(f"\n2. Acme asks: {QUESTION}")
    body = api(
        "POST", f"/v1/organizations/{acme_org}/chat", acme, json={"question": QUESTION}
    ).json()
    print(f"\n   {body['answer']}\n")
    for c in body["citations"]:
        print(f"   [{c['position']}] {c['document_title']} v{c['version']} · {c['section']}")
    for conflict in body["conflicts"]:
        for d in conflict["documents"]:
            print(
                f"   - {d['policy_id'] or d['title']}: {d['status']} ({d['reason'] or 'current'})"
            )
    statuses = {d["title"]: d["status"] for c in body["conflicts"] for d in c["documents"]}
    titles = {c["document_title"] for c in body["citations"]}
    check(
        body["status"] == "answered" and "10 days" in body["answer"],
        "answer gives the premium 10-day window",
    )
    check("premium-support-policy" in titles, "cites the premium exception")
    check(statuses.get("refund-policy-2024") == "superseded", "2024 policy marked superseded")
    check("refund-policy-2024" not in titles, "does not cite the superseded policy")

    print("\n3. Nova tries to reach Acme")
    doc_id = docs[0]["id"]
    check(
        api("GET", f"/v1/organizations/{acme_org}/documents", nova).status_code == 404,
        "Nova cannot list Acme's documents",
    )
    check(
        api("GET", f"/v1/organizations/{acme_org}/documents/{doc_id}", nova).status_code == 404,
        "Nova cannot read an Acme document",
    )
    check(
        api("GET", f"/v1/organizations/{nova_org}/documents/{doc_id}", nova).status_code == 404,
        "Nova cannot reach it by putting it under its own workspace",
    )
    check(
        api("DELETE", f"/v1/organizations/{acme_org}/documents/{doc_id}", nova).status_code == 404,
        "Nova cannot delete it",
    )
    nova_answer = api(
        "POST", f"/v1/organizations/{nova_org}/chat", nova, json={"question": QUESTION}
    ).json()
    check(
        nova_answer["status"] == "insufficient_evidence" and not nova_answer["citations"],
        "Nova's chat finds none of Acme's evidence",
    )

    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
