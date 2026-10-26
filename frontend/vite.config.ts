/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` serves the UI on :5173 and forwards /api to the FastAPI app on :8000.
// `npm run build` writes frontend/dist, which FastAPI serves in production.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: { outDir: "dist" },
  test: { environment: "jsdom", globals: true, setupFiles: ["tests/setup.ts"] },
});
