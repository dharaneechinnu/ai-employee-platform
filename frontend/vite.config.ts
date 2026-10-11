import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Where the dev proxy forwards /api. Inside Docker the API is reachable
// by its service name; `localhost` there is the web container itself,
// not the API, so the request would never leave the box.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Proxying keeps the browser on one origin, so the httpOnly refresh
    // cookie is sent like a same-site cookie and needs no CORS dance.
    proxy: { "/api": { target: API_TARGET, changeOrigin: true } },
  },
});
