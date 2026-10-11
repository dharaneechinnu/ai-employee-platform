import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The API runs in its own container; proxying keeps the browser on
    // one origin so the httpOnly refresh cookie is sent normally.
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
});
