import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In dev, proxy API + WebSocket traffic to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
