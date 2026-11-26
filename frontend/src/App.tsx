import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { AuthProvider, useAuth } from "./hooks/useAuth";
import { OrgsProvider } from "./hooks/useOrgs";
import { LoginPage, SignupPage } from "./pages/AuthPages";
import { AuditLogPage } from "./pages/AuditLogPage";
import { ChatPage } from "./pages/ChatPage";
import { DemoPage } from "./pages/DemoPage";
import { EvaluationsPage } from "./pages/EvaluationsPage";
import { InvitePage } from "./pages/InvitePage";
import { KnowledgeBasePage } from "./pages/KnowledgeBasePage";
import { MembersPage } from "./pages/MembersPage";
import { OrgPickerPage } from "./pages/OrgPickerPage";
import { UsagePage } from "./pages/UsagePage";

function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="center"><Spinner /></div>;
  if (!session) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <OrgsProvider>{children}</OrgsProvider>;
}

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/demo" element={<DemoPage />} />
          <Route path="/invite/:token" element={<RequireAuth><InvitePage /></RequireAuth>} />
          <Route path="/" element={<RequireAuth><OrgPickerPage /></RequireAuth>} />
          <Route path="/workspaces" element={<RequireAuth><OrgPickerPage forceList /></RequireAuth>} />
          <Route path="/o/:orgId" element={<RequireAuth><Layout /></RequireAuth>}>
            <Route index element={<Navigate to="chat" replace />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:conversationId" element={<ChatPage />} />
            <Route path="documents" element={<KnowledgeBasePage />} />
            <Route path="members" element={<MembersPage />} />
            <Route path="usage" element={<UsagePage />} />
            <Route path="audit" element={<AuditLogPage />} />
            <Route path="evaluations" element={<EvaluationsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
