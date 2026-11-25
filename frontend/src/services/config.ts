// Runtime configuration. Defaults assume one origin: the app, the API (/v1)
// and Supabase Auth (/auth/v1) behind the same host (nginx or the Vite proxy).
export const config = {
  supabaseUrl: import.meta.env.VITE_SUPABASE_URL || window.location.origin,
  supabaseAnonKey: import.meta.env.VITE_SUPABASE_ANON_KEY || "",
  apiUrl: (import.meta.env.VITE_API_URL || "").replace(/\/$/, ""),
};
