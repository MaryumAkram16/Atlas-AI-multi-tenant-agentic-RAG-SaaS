import { useCallback, useEffect, useState } from "react";
import { Badge, EmptyState, formatDate } from "../../components/ui";
import { apiRequest } from "../../services/api";
import { parseFacts } from "../../services/format";
import type { EvalDataset, FeedbackReview } from "../../services/types";
import { REASONS } from "../chat/FeedbackBar";

/** Answer feedback from members; a thumbs down can become an evaluation case. */
export function FeedbackReviewList({ base, token, datasets, onCaseAdded, onError }: {
  base: string;
  token: string | null;
  datasets: EvalDataset[];
  onCaseAdded: () => Promise<void> | void;
  onError: (message: string) => void;
}) {
  const [rating, setRating] = useState<"down" | "up" | "">("down");
  const [rows, setRows] = useState<FeedbackReview[]>([]);
  const [added, setAdded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const q = rating ? `?rating=${rating}` : "";
      setRows(await apiRequest<FeedbackReview[]>(`${base}/feedback${q}`, token));
    } catch (e) {
      onError((e as Error).message);
    }
  }, [base, token, rating, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="card" aria-label="Answer feedback">
      <div className="row between">
        <h2 className="card-title">Answer feedback</h2>
        <select aria-label="Feedback filter" value={rating} onChange={(e) => setRating(e.target.value as "down" | "up" | "")}>
          <option value="down">Not helpful</option>
          <option value="up">Helpful</option>
          <option value="">All</option>
        </select>
      </div>
      <p className="muted small">Questions members rated. Turn a bad answer into a test case so you can tell when it's fixed.</p>
      {rows.length === 0 ? (
        <EmptyState title="No feedback yet" />
      ) : (
        <table className="table compact">
          <thead><tr><th>Question</th><th>Feedback</th><th>From</th><th>When</th><th /></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.message_id}-${r.user_id}`}>
                <td>{r.question}</td>
                <td className="small">
                  <Badge tone={r.rating === "up" ? "teal" : "red"}>{r.rating === "up" ? "helpful" : "not helpful"}</Badge>{" "}
                  {r.reason && REASONS.find((x) => x.value === r.reason)?.label}
                  {r.comment && <div className="muted">“{r.comment}”</div>}
                </td>
                <td className="small">{r.email ?? "Former member"}</td>
                <td className="small nowrap">{formatDate(r.created_at)}</td>
                <td>
                  {r.rating === "down" && (added.has(r.message_id) ? <span className="muted small">Added</span> : (
                    <AddCase datasets={datasets} question={r.question} onAdd={async (datasetId, facts, abstain) => {
                      await apiRequest(`${base}/evaluation-datasets/${datasetId}/cases`, token, {
                        method: "POST",
                        body: { cases: [{ question: r.question, expected_facts: abstain ? [] : facts, should_abstain: abstain }] },
                      });
                      setAdded((s) => new Set(s).add(r.message_id));
                      await onCaseAdded();
                    }} onError={onError} />
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function AddCase({ datasets, question, onAdd, onError }: {
  datasets: EvalDataset[];
  question: string;
  onAdd: (datasetId: string, facts: string[], abstain: boolean) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState("");
  // Datasets may load after this row mounts: default to the first one.
  const datasetId = datasets.some((d) => d.id === picked) ? picked : (datasets[0]?.id ?? "");
  const [facts, setFacts] = useState("");
  const [abstain, setAbstain] = useState(false);
  if (datasets.length === 0) return <span className="muted small">Create a dataset first</span>;
  if (!open) {
    return <button className="btn" onClick={() => setOpen(true)} aria-label={`Add "${question}" to a dataset`}>Add to dataset</button>;
  }
  const valid = datasetId && (abstain || parseFacts(facts).length > 0);
  return (
    <div className="add-case">
      <select aria-label="Dataset" value={datasetId} onChange={(e) => setPicked(e.target.value)}>
        {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>
      <input aria-label="Correct facts" placeholder="Facts a correct answer contains" value={facts}
        disabled={abstain} onChange={(e) => setFacts(e.target.value)} />
      <label className="row small">
        <input type="checkbox" checked={abstain} onChange={(e) => setAbstain(e.target.checked)} />
        Should abstain
      </label>
      <button className="btn btn-primary" disabled={!valid} onClick={() => {
        onAdd(datasetId, parseFacts(facts), abstain).catch((e: Error) => onError(e.message));
      }}>Add case</button>
    </div>
  );
}
