# API reference

Generated from the FastAPI app by `scripts/generate_api_reference.py`; the full
schema is in [`openapi.json`](openapi.json). Every `/v1` endpoint needs
`Authorization: Bearer <Supabase JWT>`, and every `/v1/organizations/{org_id}/...`
endpoint also needs an active membership in that organization (non-members get 404).

Errors always have the shape
`{"error": {"code": "...", "message": "...", "request_id": "..."}}`; common codes:
`unauthenticated` (401), `forbidden` (403), `not_found` (404), `conflict` /
`duplicate_document` (409), `payload_too_large` (413), `unsupported_media_type` (415),
`validation_error` (422), `rate_limited` / `quota_exceeded` (429).

| Method | Path | Summary | Auth |
|---|---|---|---|
| GET | `/health` | Liveness: the process is up. Does not touch dependencies. | none |
| GET | `/ready` | Readiness: Postgres and Qdrant are reachable. | none |
| GET | `/v1/organizations` | List Organizations | signed in |
| POST | `/v1/organizations` | Create Organization | signed in |
| GET | `/v1/organizations/{org_id}` | Get Organization | member |
| GET | `/v1/organizations/{org_id}/members` | List Members | member |
| POST | `/v1/organizations/{org_id}/members` | Invite Member | member |
| PATCH | `/v1/organizations/{org_id}/members/{member_id}` | Change Member Role | member |
| DELETE | `/v1/organizations/{org_id}/members/{member_id}` | Revoke Member | member |
| GET | `/v1/organizations/{org_id}/invitations` | List Invitations | member |
| POST | `/v1/invitations/accept` | Accept Invitation | signed in |
| POST | `/v1/organizations/{org_id}/documents` | Upload Document | member |
| GET | `/v1/organizations/{org_id}/documents` | List Documents | member |
| GET | `/v1/organizations/{org_id}/documents/{document_id}` | Get Document | member |
| DELETE | `/v1/organizations/{org_id}/documents/{document_id}` | Delete Document | member |
| POST | `/v1/organizations/{org_id}/documents/{document_id}/versions` | Upload Version | member |
| POST | `/v1/organizations/{org_id}/documents/{document_id}/reindex` | Reindex Document | member |
| GET | `/v1/organizations/{org_id}/documents/{document_id}/versions/{version_id}/download-url` | Download Url | member |
| GET | `/v1/organizations/{org_id}/documents/{document_id}/chunks/{chunk_id}` | Text of one cited chunk, for source previews (readers only, via RLS). | member |
| GET | `/v1/organizations/{org_id}/jobs/{job_id}` | Get Job | member |
| POST | `/v1/organizations/{org_id}/chat` | Chat | member |
| GET | `/v1/organizations/{org_id}/conversations` | List Conversations | member |
| GET | `/v1/organizations/{org_id}/conversations/{conversation_id}` | Get Conversation | member |
| GET | `/v1/organizations/{org_id}/usage` | Your own usage; owners and admins also get organization totals and quotas. | member |
| GET | `/v1/organizations/{org_id}/audit-logs` | Owners and admins; newest first. Page with `before_id`. | member |
| GET | `/v1/files/{path}` | Serves local-storage files for signed URLs (dev/test backend only). | none (signed URL) |

`POST /v1/organizations/{org_id}/chat` streams Server-Sent Events when the request has
`Accept: text/event-stream`: `meta` (conversation and message IDs), `step` (agent node
names while it works), `delta` (verified answer text), `citations`, `done` (status,
evidence status, conflicts, retrieval attempts, trace ID, usage) and `error`.
