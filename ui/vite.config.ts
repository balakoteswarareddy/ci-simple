import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API calls to the backend so the browser never talks to
// localhost ports directly (same-origin in prod via nginx, proxy here).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    // Allow the sandboxed browser-preview proxy ( *.e2b.app ) in addition to
    // localhost; without this Vite 403s the preview with "host not allowed".
    allowedHosts: ["localhost", ".e2b.app"],
    proxy: {
      "/api": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
      "/readyz": "http://localhost:8000",
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 4173,
  },
});
