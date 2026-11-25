import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { apiRequest } from "../services/api";
import type { Organization } from "../services/types";
import { useAuth } from "./useAuth";

interface OrgsState {
  orgs: Organization[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const OrgsContext = createContext<OrgsState | null>(null);

export function OrgsProvider({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!token) {
      setOrgs([]);
      setLoading(false);
      return;
    }
    try {
      setOrgs(await apiRequest<Organization[]>("/v1/organizations", token));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <OrgsContext.Provider value={{ orgs, loading, error, refresh }}>{children}</OrgsContext.Provider>
  );
}

export function useOrgs(): OrgsState {
  const ctx = useContext(OrgsContext);
  if (!ctx) throw new Error("useOrgs outside OrgsProvider");
  return ctx;
}
