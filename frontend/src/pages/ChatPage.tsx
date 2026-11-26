import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { ErrorBanner, Spinner } from "../components/ui";
import { MessageView } from "../features/chat/MessageView";
import { SourcePreview } from "../features/chat/SourcePreview";
import { useAuth } from "../hooks/useAuth";
import { apiRequest } from "../services/api";
import { postSSE } from "../services/sse";
import type {
  AnswerStatus, ChatMessage, Citation, Conflict, Conversation, ConversationDetail, Organization, Explanation } from "../services/types";

export const STEP_LABELS: Record<string, string> = {
  validate_context: "Checking access",
  classify_intent: "Understanding the question",
  plan_retrieval: "Planning the search",
  decompose_query: "Planning the search",
  retrieve_documents: "Searching documents",
  validate_permissions: "Checking document permissions",
  rerank_results: "Ranking evidence",
  assess_evidence: "Assessing evidence",
  rewrite_query: "Refining the search",
  detect_conflicts: "Comparing sources",
  compare_versions: "Comparing versions and dates",
  generate_answer: "Writing the answer",
  verify_citations: "Verifying citations",
  finalize_response: "Finishing",
};

export function ChatPage() {
  const org = useOutletContext<Organization>();
  const { conversationId } = useParams();
  const { token } = useAuth();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [step, setStep] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Citation | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const base = `/v1/organizations/${org.id}`;

  const loadConversations = useCallback(async () => {
    setConversations(await apiRequest<Conversation[]>(`${base}/conversations`, token));
  }, [base, token]);

  useEffect(() => {
    void loadConversations().catch((e: Error) => setError(e.message));
  }, [loadConversations]);

  useEffect(() => {
    setPreview(null);
    if (!conversationId) return setMessages([]);
    if (pending) return; // the stream owns the message list while answering
    apiRequest<ConversationDetail>(`${base}/conversations/${conversationId}`, token)
      .then((c) => setMessages(c.messages.map((m) => ({ ...m, conflicts: m.conflicts ?? [] }))))
      .catch((e: Error) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, conversationId, token]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, step]);

  async function ask(e: FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || !token || pending) return;
    setQuestion("");
    setError(null);
    setPending(true);
    setStep(null);
    const answer: ChatMessage = { id: "pending", role: "assistant", content: "", status: null, citations: [], conflicts: [] };
    setMessages((m) => [...m, { id: `u-${Date.now()}`, role: "user", content: q, status: null, citations: [], conflicts: [] }, answer]);
    const update = (patch: Partial<ChatMessage>) =>
      setMessages((m) => m.map((x) => (x.id === "pending" ? { ...x, ...patch } : x)));
    let newConversation: string | null = null;
    try {
      let text = "";
      for await (const ev of postSSE(`${base}/chat`, token, { question: q, conversation_id: conversationId ?? null })) {
        const data = ev.data as Record<string, unknown>;
        if (ev.event === "meta" && !conversationId) newConversation = String(data.conversation_id);
        else if (ev.event === "step") setStep(String(data.node));
        else if (ev.event === "delta") {
          text += String(data.text);
          setStep(null);
          update({ content: text });
        } else if (ev.event === "citations") update({ citations: data.citations as Citation[] });
        else if (ev.event === "done") {
          update({
            id: `a-${Date.now()}`,
            status: data.status as AnswerStatus,
            conflicts: (data.conflicts as Conflict[]) ?? [],
            evidence_status: data.evidence_status as string,
            retrieval_attempts: data.retrieval_attempts as number,
            trace_id: data.trace_id as string,
            explanation: (data.explanation as Explanation | null) ?? null,
          });
        }
      }
    } catch (err) {
      setError((err as Error).message);
      setMessages((m) => m.filter((x) => x.id !== "pending"));
    } finally {
      setPending(false);
      setStep(null);
      void loadConversations();
      if (newConversation) navigate(`/o/${org.id}/chat/${newConversation}`, { replace: true });
    }
  }

  return (
    <div className={`chat ${preview ? "with-preview" : ""}`}>
      <aside className="conversations" aria-label="Conversations">
        <Link className="btn btn-primary" to={`/o/${org.id}/chat`}>New chat</Link>
        <ul className="list">
          {conversations.map((c) => (
            <li key={c.id} className={c.id === conversationId ? "active" : ""}>
              <Link to={`/o/${org.id}/chat/${c.id}`}>{c.title}</Link>
            </li>
          ))}
        </ul>
      </aside>

      <section className="thread">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">
              <h3>Ask about your documents</h3>
              <p className="muted">Answers cite their sources, flag conflicting versions, and say so when the evidence isn't there.</p>
            </div>
          )}
          {messages.map((m) =>
            m.id === "pending" && !m.content ? (
              <div key={m.id} className="msg msg-assistant msg-thinking" aria-live="polite">
                <Spinner label="Thinking" /> {step ? STEP_LABELS[step] ?? "Working" : "Starting"}…
              </div>
            ) : (
              <MessageView key={m.id} message={m} onCite={setPreview} />
            ),
          )}
          <div ref={bottom} />
        </div>
        <ErrorBanner message={error} />
        <form className="composer" onSubmit={ask}>
          <textarea aria-label="Question" placeholder="Ask a question…" value={question} maxLength={2000}
            rows={2} onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }} />
          <button className="btn btn-primary" disabled={pending || !question.trim()}>
            {pending ? "Answering…" : "Ask"}
          </button>
        </form>
      </section>

      {preview && (
        <SourcePreview orgId={org.id} citation={preview} token={token} onClose={() => setPreview(null)} />
      )}
    </div>
  );
}
