import { createClient } from "@supabase/supabase-js";
import { config } from "./config";

// Only the public anon key is ever used in the browser.
export const supabase = createClient(config.supabaseUrl, config.supabaseAnonKey || "anon", {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});
