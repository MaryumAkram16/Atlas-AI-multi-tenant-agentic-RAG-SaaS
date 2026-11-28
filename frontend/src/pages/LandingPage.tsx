import { Link } from "react-router-dom";
import { Logo } from "../components/Logo";
import { ThemeToggle } from "../components/ThemeToggle";
import { config } from "../services/config";

const USE_CASES = [
  { icon: "👥", title: "HR and people teams", body: "Leave, benefits, remote work and expenses: employees get the current rule with the policy it comes from, not last year's PDF." },
  { icon: "🎧", title: "Customer support", body: "Refund windows, warranty terms and premium exceptions resolved in one answer, with the exception and the policy it overrides both cited." },
  { icon: "🛡", title: "IT and security", body: "Password, MFA, retention and access rules answered from the security policy, and only for people allowed to read it." },
  { icon: "🧾", title: "Finance and procurement", body: "Approval limits, vendor onboarding and reimbursement caps, with effective dates so outdated limits are flagged." },
  { icon: "⚖", title: "Legal and compliance", body: "Version conflicts surface instead of being averaged away: superseded and outdated documents are named and set aside." },
  { icon: "🚀", title: "Onboarding", body: "New hires ask in plain language and every answer links back to the exact section, so they learn where the source lives." },
];

const STEPS = [
  { n: "01", title: "Upload", body: "PDF, DOCX, TXT or Markdown. Each version keeps its effective date; restricted documents stay private." },
  { n: "02", title: "Index", body: "A background worker parses, chunks and embeds every version for hybrid search (dense + BM25)." },
  { n: "03", title: "Ask", body: "A bounded agent plans the search, rechecks every passage against your permissions and rewrites weak queries." },
  { n: "04", title: "Trust the answer", body: "Verified citations, conflicting versions resolved by precedence, and a clear abstention when the evidence is not there." },
];

const TRUST = [
  { title: "Tenant isolation in Postgres", body: "Row-level security on every table; a workspace can never read another's documents, even through the search index." },
  { title: "Document permissions", body: "Restricted documents are visible only to people they are shared with. Search and answers follow the same rules." },
  { title: "Citations that are checked", body: "Every sentence is matched to a cited source before you see it; unsupported claims are removed." },
  { title: "Version conflicts resolved", body: "Explicit supersedes, scoped exceptions and effective dates decide which policy applies, and the answer shows why." },
  { title: "Prompt-injection filter", body: "Instructions hidden inside documents are dropped before any model sees them." },
  { title: "Audit log", body: "Every change, from uploads to sharing, is recorded by the database itself." },
];

const RESULTS = [
  { value: "0%", label: "outdated sources cited", note: "on conflict questions (hybrid baseline: 93.8%)" },
  { value: "87.5%", label: "correct abstentions", note: "when the documents do not contain the answer" },
  { value: "100%", label: "injection resistance", note: "on documents with hidden instructions" },
];

const FAQ = [
  { q: "Where do answers come from?", a: "Only from documents in your workspace that you are allowed to read. If the evidence is weak, Atlas says so instead of guessing." },
  { q: "What happens when two policies disagree?", a: "Atlas applies precedence (explicit supersedes, scoped exceptions, effective dates), uses the policy that applies and shows the others as superseded or outdated." },
  { q: "Can people see documents they should not?", a: "No. Permissions are enforced in the database on every request, and every passage is rechecked before it reaches the model." },
  { q: "How were the results above measured?", a: "On a 111-question labelled benchmark over a synthetic policy corpus, run offline. They measure behaviour such as citations and abstention, not answer quality with a specific model." },
];

export function LandingPage() {
  const tryLink = config.demoEnabled ? "/demo" : "/signup";
  return (
    <div className="landing">
      <header className="landing-header">
        <div className="landing-container landing-nav">
          <Logo size={32} />
          <nav className="landing-links" aria-label="Sections">
            <a href="#use-cases">Use cases</a>
            <a href="#how">How it works</a>
            <a href="#trust">Security</a>
            <a href="#faq">FAQ</a>
          </nav>
          <div className="row">
            <ThemeToggle />
            <Link className="btn btn-ghost landing-signin" to="/login">Sign in</Link>
            <Link className="btn btn-primary landing-cta-small" to="/signup">Get started</Link>
          </div>
        </div>
      </header>

      <section className="landing-hero">
        <div className="landing-scanlines" aria-hidden />
        <div className="landing-orb" aria-hidden />
        <div className="landing-container landing-hero-grid">
          <div>
            <span className="eyebrow"><span className="eyebrow-dot" />Agentic RAG for company knowledge</span>
            <h1 className="landing-title">
              Answers your team can <span className="gradient-text">trust</span>, straight from your documents.
            </h1>
            <p className="landing-lead">
              Atlas reads your policies, handbooks and contracts, answers in plain language with verified
              citations, resolves conflicting versions, and says so when the evidence is not there.
            </p>
            <div className="row wrap landing-ctas">
              <Link className="btn btn-primary btn-lg" to="/signup">Create a workspace →</Link>
              <Link className="btn btn-lg" to={tryLink}>{config.demoEnabled ? "Explore the demo" : "Sign up free"}</Link>
            </div>
            <p className="landing-note">Citations on every answer · Abstains when unsure · Workspaces isolated</p>
          </div>

          <div className="landing-preview" aria-label="Example answer">
            <div className="preview-label">Example answer</div>
            <div className="preview-question">A premium customer bought something 8 days ago. Can they still get a refund?</div>
            <div className="preview-answer">
              Yes. Premium plan customers may request a refund within 10 days of purchase, overriding the
              standard 7-day window <span className="cite">1</span>
            </div>
            <div className="preview-conflict">
              <strong>Sources disagree; resolved by precedence</strong>
              <ul>
                <li><span className="badge badge-violet">exception</span> Premium support policy · 10 days</li>
                <li><span className="badge badge-teal">current</span> Refund policy 2026 · 7 days</li>
                <li><span className="badge badge-slate">superseded</span> Refund policy 2024 · 14 days</li>
              </ul>
            </div>
            <div className="preview-source"><span className="cite">1</span> premium-support-policy v1 · effective Feb 1, 2026</div>
          </div>
        </div>
      </section>

      <section id="use-cases" className="landing-section">
        <div className="landing-container">
          <span className="section-kicker">Use cases</span>
          <h2 className="section-title">One assistant for every team's documents</h2>
          <div className="landing-grid three">
            {USE_CASES.map((u) => (
              <article key={u.title} className="feature-card">
                <div className="feature-icon" aria-hidden>{u.icon}</div>
                <h3>{u.title}</h3>
                <p className="muted">{u.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="how" className="landing-section">
        <div className="landing-container">
          <span className="section-kicker">How it works</span>
          <h2 className="section-title">From upload to a cited answer</h2>
          <div className="landing-grid four">
            {STEPS.map((s) => (
              <article key={s.n} className="step-card">
                <span className="step-n">{s.n}</span>
                <h3>{s.title}</h3>
                <p className="muted">{s.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="trust" className="landing-section">
        <div className="landing-container">
          <span className="section-kicker">Security and accuracy</span>
          <h2 className="section-title">Built so the right people get the right answer</h2>
          <div className="landing-grid three">
            {TRUST.map((t) => (
              <article key={t.title} className="feature-card compact">
                <h3>{t.title}</h3>
                <p className="muted">{t.body}</p>
              </article>
            ))}
          </div>
          <div className="landing-results">
            {RESULTS.map((r) => (
              <div key={r.label} className="result">
                <span className="result-value gradient-text">{r.value}</span>
                <span className="result-label">{r.label}</span>
                <span className="muted small">{r.note}</span>
              </div>
            ))}
          </div>
          <p className="muted small landing-footnote">
            Measured offline on a 111-question labelled benchmark (synthetic policy corpus). See the evaluation report in
            the repository for every metric and its caveats.
          </p>
        </div>
      </section>

      <section id="faq" className="landing-section">
        <div className="landing-container landing-faq">
          <span className="section-kicker">FAQ</span>
          <h2 className="section-title">Questions teams ask first</h2>
          {FAQ.map((f) => (
            <details key={f.q} className="faq-item">
              <summary>{f.q}</summary>
              <p className="muted">{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="landing-final">
        <div className="landing-scanlines" aria-hidden />
        <div className="landing-orb small" aria-hidden />
        <div className="landing-container landing-final-inner">
          <h2 className="landing-title small">Ask your documents.</h2>
          <p className="landing-lead">Create a workspace, upload a few policies and get your first cited answer in minutes.</p>
          <div className="row wrap landing-ctas center-row">
            <Link className="btn btn-primary btn-lg" to="/signup">Create a workspace →</Link>
            {config.demoEnabled && <Link className="btn btn-lg" to="/demo">Explore the demo</Link>}
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="landing-container row between wrap">
          <Logo size={26} />
          <nav className="landing-links" aria-label="Footer">
            <a href="#use-cases">Use cases</a>
            <a href="#how">How it works</a>
            <a href="#trust">Security</a>
            <a href="#faq">FAQ</a>
            <Link to="/login">Sign in</Link>
          </nav>
          <span className="muted small">© 2026 Atlas AI</span>
        </div>
      </footer>
    </div>
  );
}
