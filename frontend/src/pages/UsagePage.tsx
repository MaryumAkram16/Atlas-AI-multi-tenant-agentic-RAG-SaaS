import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { ErrorBanner, Spinner } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { apiRequest } from "../services/api";
import { bytes, count, money, usageShare } from "../services/format";
import type { Organization, QuotaItem, Usage, UsageTotals } from "../services/types";

const PERIODS = [7, 30, 90];

export function UsagePage() {
  const org = useOutletContext<Organization>();
  const { token } = useAuth();
  const [days, setDays] = useState(30);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    apiRequest<Usage>(`/v1/organizations/${org.id}/usage?days=${days}`, token)
      .then(setUsage)
      .catch((e: Error) => setError(e.message));
  }, [org.id, token, days]);

  return (
    <section className="page">
      <header className="page-head">
        <h1>Usage</h1>
        <label className="row small muted">
          Period
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {PERIODS.map((d) => <option key={d} value={d}>Last {d} days</option>)}
          </select>
        </label>
      </header>
      <ErrorBanner message={error} />
      {!usage ? (
        !error && <Spinner />
      ) : (
        <>
          <Totals title="You" totals={usage.me} />
          {usage.organization && <Totals title="Whole workspace" totals={usage.organization} />}
          {usage.quota && (
            <div className="card">
              <h2 className="card-title">Plan limits ({usage.quota.plan})</h2>
              <QuotaMeter label="Questions in the last 24 hours" item={usage.quota.questions_per_day} />
              <QuotaMeter label="Documents" item={usage.quota.documents} />
              <QuotaMeter label="Storage" item={usage.quota.storage_bytes} format={bytes} />
            </div>
          )}
          <p className="muted small">
            Each question counts once, including evaluation cases. Cost is shown only when model
            prices are configured on the server.
          </p>
        </>
      )}
    </section>
  );
}

function Totals({ title, totals }: { title: string; totals: UsageTotals }) {
  return (
    <div className="card">
      <h2 className="card-title">{title}</h2>
      <div className="tiles">
        <Tile label="Questions" value={count(totals.questions)} />
        <Tile label="Input tokens" value={count(totals.prompt_tokens)} />
        <Tile label="Output tokens" value={count(totals.completion_tokens)} />
        <Tile label="Estimated cost" value={money(totals.estimated_cost)} />
      </div>
    </div>
  );
}

export function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="tile">
      <span className="tile-value">{value}</span>
      <span className="tile-label">{label}</span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  );
}

function QuotaMeter({ label, item, format = count }: {
  label: string;
  item: QuotaItem;
  format?: (v: number) => string;
}) {
  const share = usageShare(item);
  const near = share !== null && share >= 0.9;
  return (
    <div className="quota">
      <div className="row between small">
        <span>{label}</span>
        <span>
          {format(item.used)} {item.limit === null ? "(unlimited)" : `of ${format(item.limit)}`}
          {near && <strong className="quota-warn"> · near the limit</strong>}
        </span>
      </div>
      {share !== null && (
        <div className="meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={item.limit ?? 0}
          aria-valuenow={item.used}>
          <span className={near ? "meter-fill meter-warn" : "meter-fill"} style={{ width: `${share * 100}%` }} />
        </div>
      )}
    </div>
  );
}
