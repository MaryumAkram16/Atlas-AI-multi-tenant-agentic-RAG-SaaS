/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, Vite proxies the API and Supabase Auth so the app runs on one
// origin, exactly like the nginx container does in docker compose.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://localhost:8000",
      "/auth/v1": {
        target: "http://localhost:9999",
        rewrite: (path) => path.replace(/^\/auth\/v1/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
