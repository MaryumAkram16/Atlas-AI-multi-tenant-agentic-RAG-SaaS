import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useOutletContext } from "react-router-dom";
import { Badge, EmptyState, ErrorBanner, STATUS_TONE, formatDate } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { apiRequest } from "../services/api";
import { count, money, parseFacts, percent } from "../services/format";
import type { DocumentItem, EvalDataset, EvalResult, EvalRun, Organization } from "../services/types";
import { FeedbackReviewList } from "../features/evaluations/FeedbackReview";
import { Tile } from "./UsagePage";

interface DraftCase {
  question: string;
  facts: string;
  documentId: string;
  shouldAbstain: boolean;
}

const EMPTY_CASE: DraftCase = { question: "", facts: "", documentId: "", shouldAbstain: false };

export function EvaluationsPage() {
  const org = useOutletContext<Organization>();
  const { token } = useAuth();
  const base = `/v1/organizations/${org.id}`;
  const [datasets, setDatasets] = useState<EvalDataset[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [selected, setSelected] = useState<EvalDataset | null>(null);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [d, r, docList] = await Promise.all([
        apiRequest<EvalDataset[]>(`${base}/evaluation-datasets`, token),
        apiRequest<EvalRun[]>(`${base}/evaluations`, token),
        apiRequest<DocumentItem[]>(`${base}/documents`, token),
      ]);
      setDatasets(d);
      setRuns(r);
      setDocs(docList.filter((x) => x.status === "ready"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [base, token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act<T>(action: () => Promise<T>): Promise<T | undefined> {
    setError(null);
    try {
      return await action();
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    }
  }

  async function openDataset(id: string) {
    const d = await act(() => apiRequest<EvalDataset>(`${base}/evaluation-datasets/${id}`, token));
    if (d) setSelected(d);
  }

  async function startRun(dataset: EvalDataset) {
    setRunning(dataset.id);
    const result = await act(() => apiRequest<EvalRun>(`${base}/evaluations`, token, {
      method: "POST", body: { dataset_id: dataset.id } }));
    setRunning(null);
    if (result) setRun(result);
    await load();
  }

  const docTitle = (id: string) => docs.find((d) => d.id === id)?.title ?? "Unavailable document";

  return (
    <section className="page">
      <header className="page-head">
        <h1>Evaluations</h1>
        <span className="muted small">Benchmark the assistant on your own documents</span>
      </header>
      <ErrorBanner message={error} />

      <NewDataset docs={docs} onCreate={async (body) => {
        const d = await act(() => apiRequest<EvalDataset>(`${base}/evaluation-datasets`, token, {
          method: "POST", body }));
        if (d) {
          setSelected(d);
          await load();
        }
        return Boolean(d);
      }} />

      <h2>Datasets</h2>
      {datasets.length === 0 ? (
        <EmptyState title="No datasets yet">
          <p className="muted">Add questions with the facts a good answer must contain.</p>
        </EmptyState>
      ) : (
        <table className="table" aria-label="Evaluation datasets">
          <thead><tr><th>Name</th><th>Cases</th><th>Updated</th><th /></tr></thead>
          <tbody>
            {datasets.map((d) => (
              <tr key={d.id}>
                <td><button className="link" onClick={() => void openDataset(d.id)}>{d.name}</button></td>
                <td>{d.case_count}</td>
                <td>{formatDate(d.updated_at)}</td>
                <td className="row">
                  <button className="btn btn-primary" disabled={running !== null || d.case_count === 0}
                    onClick={() => void startRun(d)}>
                    {running === d.id ? "Running…" : "Run"}
                  </button>
                  <button className="btn btn-ghost" onClick={() => {
                    if (!window.confirm(`Delete dataset "${d.name}"? Past runs are kept.`)) return;
                    void act(() => apiRequest(`${base}/evaluation-datasets/${d.id}`, token, { method: "DELETE" }))
                      .then(() => { if (selected?.id === d.id) setSelected(null); return load(); });
                  }}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {selected && (
        <div className="card" aria-label="Dataset cases">
          <h2 className="card-title">{selected.name}: cases</h2>
          <table className="table compact">
            <thead><tr><th>Question</th><th>Expected</th><th /></tr></thead>
            <tbody>
              {(selected.cases ?? []).map((c) => (
                <tr key={c.id}>
                  <td>{c.question}</td>
                  <td className="small">
                    {c.should_abstain ? "Should say there is not enough evidence" : c.expected_facts.join(", ")}
                    {c.expected_document_ids.length > 0 && (
                      <span className="muted"> · cites {c.expected_document_ids.map(docTitle).join(", ")}</span>
                    )}
                  </td>
                  <td>
                    <button className="btn btn-ghost" onClick={() => void act(() =>
                      apiRequest(`${base}/evaluation-datasets/${selected.id}/cases/${c.id}`, token, { method: "DELETE" }))
                      .then(() => openDataset(selected.id)).then(load)}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <CaseForm docs={docs} submitLabel="Add case" onSubmit={async (c) => {
            const d = await act(() => apiRequest<EvalDataset>(`${base}/evaluation-datasets/${selected.id}/cases`,
              token, { method: "POST", body: { cases: [toPayload(c)] } }));
            if (d) {
              setSelected(d);
              await load();
            }
            return Boolean(d);
          }} />
        </div>
      )}

      <FeedbackReviewList base={base} token={token} datasets={datasets} onError={setError}
        onCaseAdded={async () => {
          await load();
          if (selected) await openDataset(selected.id);
        }} />

      <h2>Runs</h2>
      {runs.length === 0 ? (
        <p className="muted">No runs yet.</p>
      ) : (
        <table className="table" aria-label="Evaluation runs">
          <thead>
            <tr><th>Started</th><th>Dataset</th><th>Status</th><th>Fact accuracy</th><th>Abstention</th><th>Cited expected</th><th>p95</th></tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="clickable" onClick={() =>
                void act(() => apiRequest<EvalRun>(`${base}/evaluations/${r.id}`, token)).then((x) => x && setRun(x))}>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.dataset_name}</td>
                <td><Badge tone={STATUS_TONE[r.status] ?? "slate"}>{r.status}</Badge></td>
                <td>{percent(r.metrics?.fact_accuracy)}</td>
                <td>{percent(r.metrics?.abstention_accuracy)}</td>
                <td>{percent(r.metrics?.evidence_hit_rate)}</td>
                <td>{r.metrics?.latency_p95_ms != null ? `${r.metrics.latency_p95_ms} ms` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {run && <RunDetail run={run} docTitle={docTitle} />}
    </section>
  );
}

function toPayload(c: DraftCase) {
  return {
    question: c.question.trim(),
    expected_facts: c.shouldAbstain ? [] : parseFacts(c.facts),
    expected_document_ids: !c.shouldAbstain && c.documentId ? [c.documentId] : [],
    should_abstain: c.shouldAbstain,
  };
}

function NewDataset({ docs, onCreate }: {
  docs: DocumentItem[];
  onCreate: (body: Record<string, unknown>) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  const [cases, setCases] = useState<DraftCase[]>([]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    if (await onCreate({ name: name.trim(), cases: cases.map(toPayload) })) {
      setName("");
      setCases([]);
    }
  }

  return (
    <form className="card" onSubmit={create} aria-label="New dataset">
      <h2 className="card-title">New dataset</h2>
      <label className="row small">
        Name
        <input aria-label="Dataset name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
      </label>
      {cases.length > 0 && (
        <ol className="small">
          {cases.map((c, i) => (
            <li key={i}>
              {c.question} <span className="muted">→ {c.shouldAbstain ? "abstain" : parseFacts(c.facts).join(", ")}</span>
            </li>
          ))}
        </ol>
      )}
      <CaseForm docs={docs} submitLabel="Add to list" onSubmit={async (c) => {
        setCases((list) => [...list, c]);
        return true;
      }} />
      <button className="btn btn-primary" disabled={!name.trim()}>Create dataset</button>
    </form>
  );
}

function CaseForm({ docs, submitLabel, onSubmit }: {
  docs: DocumentItem[];
  submitLabel: string;
  onSubmit: (c: DraftCase) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<DraftCase>(EMPTY_CASE);
  const valid = draft.question.trim() !== "" &&
    (draft.shouldAbstain || parseFacts(draft.facts).length > 0 || draft.documentId !== "");

  async function add() {
    if (valid && (await onSubmit(draft))) setDraft(EMPTY_CASE);
  }

  return (
    <div className="row wrap case-form">
      <input aria-label="Case question" placeholder="Question" value={draft.question}
        onChange={(e) => setDraft({ ...draft, question: e.target.value })} />
      <input aria-label="Expected facts" placeholder="Facts the answer must contain (comma separated)"
        value={draft.facts} disabled={draft.shouldAbstain}
        onChange={(e) => setDraft({ ...draft, facts: e.target.value })} />
      <select aria-label="Expected source" value={draft.documentId} disabled={draft.shouldAbstain}
        onChange={(e) => setDraft({ ...draft, documentId: e.target.value })}>
        <option value="">Any source</option>
        {docs.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
      </select>
      <label className="row small">
        <input type="checkbox" checked={draft.shouldAbstain}
          onChange={(e) => setDraft({ ...draft, shouldAbstain: e.target.checked })} />
        Not in the documents (should abstain)
      </label>
      <button type="button" className="btn" disabled={!valid} onClick={() => void add()}>{submitLabel}</button>
    </div>
  );
}

function verdict(r: EvalResult): { tone: string; label: string } {
  if (r.abstention_correct !== null) {
    return r.abstention_correct ? { tone: "teal", label: "abstained" } : { tone: "red", label: "should abstain" };
  }
  if (r.fact_hit === false) return { tone: "red", label: r.abstained ? "abstained" : "missed fact" };
  if (r.evidence_hit === false) return { tone: "violet", label: "wrong source" };
  return { tone: "teal", label: "pass" };
}

function RunDetail({ run, docTitle }: { run: EvalRun; docTitle: (id: string) => string }) {
  const m = run.metrics;
  return (
    <div className="card" aria-label="Run detail">
      <h2 className="card-title">
        {run.dataset_name} · {new Date(run.created_at).toLocaleString()}{" "}
        <Badge tone={STATUS_TONE[run.status] ?? "slate"}>{run.status}</Badge>
      </h2>
      {run.error && <p className="muted">{run.error}</p>}
      {m && (
        <div className="tiles">
          <Tile label="Fact accuracy" value={percent(m.fact_accuracy)} hint="answer contains every expected fact" />
          <Tile label="False abstention" value={percent(m.false_abstention)} hint="answerable, but abstained" />
          <Tile label="Abstention accuracy" value={percent(m.abstention_accuracy)} hint="abstained when it should" />
          <Tile label="Cited expected source" value={percent(m.evidence_hit_rate)} />
          <Tile label="Citation precision" value={percent(m.citation_precision)} />
          <Tile label="Latency p50 / p95" value={`${count(m.latency_p50_ms)} / ${count(m.latency_p95_ms)} ms`} />
          <Tile label="Tokens" value={count(m.prompt_tokens + m.completion_tokens)} />
          <Tile label="Estimated cost" value={money(m.estimated_cost)} />
        </div>
      )}
      <p className="muted small">
        Model: {String(run.config.model ?? "—")} · Fact checks are exact text matches, so correct
        paraphrases count as misses.
      </p>
      {(run.hidden_results ?? 0) > 0 && (
        <p className="banner banner-info">
          {run.hidden_results} result(s) are hidden because they used documents you cannot access.
        </p>
      )}
      <table className="table compact" aria-label="Run results">
        <thead><tr><th>#</th><th>Question</th><th>Result</th><th>Answer</th><th>Sources</th><th>Time</th></tr></thead>
        <tbody>
          {(run.results ?? []).map((r) => {
            const v = verdict(r);
            return (
              <tr key={r.position}>
                <td>{r.position}</td>
                <td>{r.question}</td>
                <td><Badge tone={v.tone}>{v.label}</Badge></td>
                <td className="small answer-cell">{r.answer || <span className="muted">({r.status})</span>}</td>
                <td className="small">{r.cited_document_ids.map(docTitle).join(", ") || "—"}</td>
                <td className="nowrap">{r.latency_ms} ms</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
