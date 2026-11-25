export type Role = "owner" | "admin" | "member" | "viewer";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  role: Role;
  created_at: string;
}

export interface Member {
  id: string;
  organization_id: string;
  user_id: string;
  email: string | null;
  role: Role;
  status: "active" | "revoked";
  invited_by: string | null;
  created_at: string;
  revoked_at: string | null;
}

export interface Invitation {
  id: string;
  organization_id: string;
  email: string;
  role: Exclude<Role, "owner">;
  invited_by: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
  token?: string;
}

export interface Version {
  id: string;
  document_id: string;
  version: number;
  filename: string;
  mime_type: string;
  size_bytes: number;
  checksum: string;
  effective_date: string | null;
  status: "pending" | "processing" | "published" | "superseded" | "failed";
  chunk_count: number | null;
  error: string | null;
  created_at: string;
  published_at: string | null;
}

export interface DocumentItem {
  id: string;
  organization_id: string;
  owner_id: string;
  title: string;
  visibility: "organization" | "restricted";
  status: "processing" | "ready" | "failed" | "deleting";
  created_at: string;
  updated_at: string;
  current_version: Version | null;
  versions?: Version[];
}

export interface Job {
  id: string;
  kind: "ingest" | "reindex" | "delete";
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  max_attempts: number;
  last_error: string | null;
}

export interface UploadAccepted {
  document: DocumentItem;
  version: Version;
  job: Job;
}

export interface Citation {
  position: number;
  chunk_id: string;
  document_id: string;
  document_title: string;
  version_id: string;
  version: number;
  effective_date: string | null;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
}

export interface ConflictDocument {
  document_id: string;
  title: string;
  policy_id: string | null;
  effective_date: string | null;
  values: string[];
  status: "current" | "superseded" | "outdated" | "exception";
  reason: string | null;
}

export interface Conflict {
  topic: string;
  resolution: "resolved" | "ambiguous" | "unresolved";
  notes: string[];
  documents: ConflictDocument[];
}

export type AnswerStatus =
  | "answered"
  | "insufficient_evidence"
  | "clarification_needed"
  | "direct"
  | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: AnswerStatus | null;
  citations: Citation[];
  conflicts: Conflict[];
  evidence_status?: string | null;
  retrieval_attempts?: number | null;
  trace_id?: string | null;
  created_at?: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}

export interface ChunkPreview {
  chunk_id: string;
  document_id: string;
  document_title: string;
  version_id: string;
  version: number;
  effective_date: string | null;
  section: string | null;
  page_start: number | null;
  page_end: number | null;
  content: string;
}
