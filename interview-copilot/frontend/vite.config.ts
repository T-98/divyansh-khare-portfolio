import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend is proxied so the browser only ever talks to one origin and the
// OpenAI key stays server-side. `host: true` exposes the dev server on the LAN,
// which is how the second device reaches it during a live interview.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
