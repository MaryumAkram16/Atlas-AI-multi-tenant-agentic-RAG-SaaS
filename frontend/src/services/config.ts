// Runtime configuration, baked in at build time.
//
// Same-origin mode (docker compose nginx, Vite dev proxy): the API (/v1) and
// Supabase Auth (/auth/v1) live on the app's own origin.
// Hosted mode (e.g. Vercel): set VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY and
// VITE_API_URL to the hosted Supabase project and API.
const env = import.meta.env;
const sameOrigin = env.DEV || env.VITE_SAME_ORIGIN === "true";

export const config = {
  supabaseUrl: env.VITE_SUPABASE_URL || window.location.origin,
  supabaseAnonKey: env.VITE_SUPABASE_ANON_KEY || "",
  apiUrl: (env.VITE_API_URL || "").replace(/\/$/, ""),
  /** False when a hosted build has no backend configured yet. */
  configured: sameOrigin || Boolean(env.VITE_SUPABASE_URL && env.VITE_API_URL),
  /** Show "Explore the demo" (needs anonymous sign-in and a demo workspace). */
  demoEnabled: env.VITE_DEMO_ENABLED === "true",
};
