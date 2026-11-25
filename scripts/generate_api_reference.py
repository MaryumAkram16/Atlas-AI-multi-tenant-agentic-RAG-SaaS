"""Regenerate docs/api/openapi.json and docs/api/README.md from the app.

python scripts/generate_api_reference.py          # write
python scripts/generate_api_reference.py --check  # fail if out of date (CI)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

AUTH_FREE = {"/health", "/ready", "/v1/files/{path}"}


def build() -> tuple[str, str]:
    settings = Settings(
        embedding_provider="hash",
        llm_provider="extractive",
        database_url="postgresql://x@127.0.0.1:1/x",
    )
    spec = create_app(settings).openapi()
    lines = [
        "# API reference",
        "",
        "Generated from the FastAPI app by `scripts/generate_api_reference.py`; the full",
        "schema is in [`openapi.json`](openapi.json). Every `/v1` endpoint needs",
        "`Authorization: Bearer <Supabase JWT>`, and every `/v1/organizations/{org_id}/...`",
        "endpoint also needs an active membership in that organization (non-members get 404).",
        "",
        "Errors always have the shape",
        '`{"error": {"code": "...", "message": "...", "request_id": "..."}}`; common codes:',
        "`unauthenticated` (401), `forbidden` (403), `not_found` (404), `conflict` /",
        "`duplicate_document` (409), `payload_too_large` (413), `unsupported_media_type` (415),",
        "`validation_error` (422), `rate_limited` / `quota_exceeded` (429).",
        "",
        "| Method | Path | Summary | Auth |",
        "|---|---|---|---|",
    ]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            summary = (op.get("description") or op.get("summary") or "").strip().splitlines()[0]
            auth = (
                "none (signed URL)"
                if path.startswith("/v1/files")
                else (
                    "none" if path in AUTH_FREE else "member" if "{org_id}" in path else "signed in"
                )
            )
            lines.append(f"| {method.upper()} | `{path}` | {summary.replace('|', '/')} | {auth} |")
    lines += [
        "",
        "`POST /v1/organizations/{org_id}/chat` streams Server-Sent Events when the request has",
        "`Accept: text/event-stream`: `meta` (conversation and message IDs), `step` (agent node",
        "names while it works), `delta` (verified answer text), `citations`, `done` (status,",
        "evidence status, conflicts, retrieval attempts, trace ID, usage) and `error`.",
        "",
    ]
    return json.dumps(spec, indent=2, sort_keys=True) + "\n", "\n".join(lines)


def main() -> None:
    spec, md = build()
    out = ROOT / "docs/api"
    if "--check" in sys.argv:
        stale = [
            p
            for p, text in [("openapi.json", spec), ("README.md", md)]
            if not (out / p).exists() or (out / p).read_text() != text
        ]
        if stale:
            sys.exit(f"API reference out of date: {stale}; run scripts/generate_api_reference.py")
        return
    out.mkdir(parents=True, exist_ok=True)
    (out / "openapi.json").write_text(spec)
    (out / "README.md").write_text(md)
    print(f"wrote {out}/openapi.json and README.md")


if __name__ == "__main__":
    main()
