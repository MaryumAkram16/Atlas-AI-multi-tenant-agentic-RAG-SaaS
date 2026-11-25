import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Logo } from "../components/Layout";
import { ErrorBanner } from "../components/ui";
import { useAuth } from "../hooks/useAuth";
import { useOrgs } from "../hooks/useOrgs";
import { ApiError, apiRequest } from "../services/api";
import type { Member } from "../services/types";

export function InvitePage() {
  const { token: inviteToken = "" } = useParams();
  const { token, email } = useAuth();
  const { refresh } = useOrgs();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const member = await apiRequest<Member>("/v1/invitations/accept", token, {
        method: "POST",
        body: { token: inviteToken },
      });
      await refresh();
      navigate(`/o/${member.organization_id}/chat`, { replace: true });
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(
        status === 404
          ? `This invitation is invalid, expired, already used, or meant for a different email than ${email}.`
          : status === 409
            ? "You are already a member of this workspace."
            : (err as Error).message,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="card auth-card">
        <Logo />
        <h1>Join a workspace</h1>
        <p className="muted">
          You were invited to an Atlas AI workspace. You are signed in as <strong>{email}</strong>;
          the invitation must have been sent to this address.
        </p>
        <ErrorBanner message={error} />
        <button className="btn btn-primary" onClick={() => void accept()} disabled={busy}>
          {busy ? "Joining…" : "Accept invitation"}
        </button>
      </div>
    </div>
  );
}
