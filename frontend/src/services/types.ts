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
  /** The caller's own access, decided by Postgres. */
  access?: DocumentAccess | null;
  current_version: Version | null;
  versions?: Version[];
}

export type DocumentAccess = "read" | "write";

export interface DocumentPermission {
  user_id: string;
  email: string | null;
  role: Role;
  member_status: "active" | "revoked";
  permission: DocumentAccess;
  granted_by: string;
  created_at: string;
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

export interface UsageTotals {
  questions: number;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost: string | null;
}

export interface QuotaItem {
  limit: number | null;
  used: number;
}

export interface Usage {
  period_days: number;
  me: UsageTotals;
  organization: UsageTotals | null;
  documents: number | null;
  storage_bytes: number | null;
  quota: {
    plan: string;
    documents: QuotaItem;
    storage_bytes: QuotaItem;
    questions_per_day: QuotaItem;
  } | null;
}

export interface AuditLog {
  id: number;
  actor_id: string | null;
  actor_type: "user" | "system";
  action: string;
  resource_type: string;
  resource_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EvalCase {
  id: string;
  question: string;
  expected_facts: string[];
  expected_document_ids: string[];
  should_abstain: boolean;
  created_at: string;
}

export interface EvalDataset {
  id: string;
  name: string;
  description: string | null;
  case_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
  cases?: EvalCase[];
}

export interface EvalMetrics {
  cases: number;
  answered_rate: number | null;
  fact_accuracy: number | null;
  false_abstention: number | null;
  abstention_accuracy: number | null;
  evidence_hit_rate: number | null;
  citation_precision: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost: number | null;
}

export interface EvalResult {
  case_id: string | null;
  position: number;
  question: string;
  status: string;
  answer: string;
  abstained: boolean;
  fact_hit: boolean | null;
  abstention_correct: boolean | null;
  evidence_hit: boolean | null;
  cited_document_ids: string[];
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
}

export interface EvalRun {
  id: string;
  dataset_id: string | null;
  dataset_name: string;
  status: "running" | "succeeded" | "failed";
  config: Record<string, unknown>;
  metrics: EvalMetrics | null;
  case_count: number;
  error: string | null;
  created_by: string;
  created_at: string;
  finished_at: string | null;
  results?: EvalResult[];
  hidden_results?: number;
}
