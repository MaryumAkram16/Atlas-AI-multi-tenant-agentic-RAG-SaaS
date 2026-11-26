import { useState } from "react";
import type { Feedback, FeedbackReason } from "../../services/types";

export const REASONS: { value: FeedbackReason; label: string }[] = [
  { value: "incorrect", label: "Incorrect" },
  { value: "missing_information", label: "Missing information" },
  { value: "wrong_citation", label: "Wrong citation" },
  { value: "outdated", label: "Used an outdated policy" },
  { value: "other", label: "Other" },
];

export interface FeedbackInput {
  rating: "up" | "down";
  reason?: FeedbackReason | null;
  comment?: string | null;
}

/** 👍/👎 under an answer. A 👎 asks for a reason and an optional comment. */
export function FeedbackBar({ value, onSave, onClear }: {
  value: Feedback | null | undefined;
  onSave: (input: FeedbackInput) => Promise<void>;
  onClear: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<FeedbackReason>(value?.reason ?? "incorrect");
  const [comment, setComment] = useState(value?.comment ?? "");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  const rated = value?.rating;
  return (
    <div className="feedback" aria-label="Answer feedback">
      <div className="row small">
        <span className="muted">Was this helpful?</span>
        <button type="button" className={`btn btn-ghost fb ${rated === "up" ? "fb-on" : ""}`} disabled={busy}
          aria-pressed={rated === "up"} aria-label="Helpful"
          onClick={() => void run(() => (rated === "up" ? onClear() : onSave({ rating: "up" })))}>👍</button>
        <button type="button" className={`btn btn-ghost fb ${rated === "down" ? "fb-on" : ""}`} disabled={busy}
          aria-pressed={rated === "down"} aria-label="Not helpful"
          onClick={() => (rated === "down" ? void run(onClear) : setOpen(true))}>👎</button>
        {rated && !open && (
          <span className="muted">
            Thanks{value?.reason ? `: ${REASONS.find((r) => r.value === value.reason)?.label.toLowerCase()}` : ""}.
          </span>
        )}
      </div>
      {open && (
        <form className="feedback-form" onSubmit={(e) => {
          e.preventDefault();
          void run(async () => {
            await onSave({ rating: "down", reason, comment: comment.trim() || null });
            setOpen(false);
          });
        }}>
          <div className="row wrap" role="radiogroup" aria-label="What went wrong?">
            {REASONS.map((r) => (
              <label key={r.value} className={`chip ${reason === r.value ? "chip-on" : ""}`}>
                <input type="radio" name="reason" value={r.value} checked={reason === r.value}
                  onChange={() => setReason(r.value)} />
                {r.label}
              </label>
            ))}
          </div>
          <textarea aria-label="Feedback comment" placeholder="What should the answer have said? (optional)"
            maxLength={1000} rows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
          <p className="muted small">
            Your question, rating and comment are shared with workspace admins to improve answers. The
            answer itself is not.
          </p>
          <div className="row">
            <button className="btn btn-primary" disabled={busy}>Send feedback</button>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}
