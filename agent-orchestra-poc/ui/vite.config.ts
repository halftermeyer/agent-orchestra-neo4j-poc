import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const gateway = process.env.GATEWAY_URL ?? "http://localhost:18000";
const cdc = process.env.CDC_URL ?? "http://localhost:18001";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // le navigateur ne parle qu'à ce serveur : passerelle (REST) et consommateur CDC (WebSocket)
      "/api": { target: gateway, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
      "/stream": { target: cdc, changeOrigin: true, ws: true, rewrite: (p) => p.replace(/^\/stream/, "") },
    },
  },
  preview: {
    proxy: {
      "/api": { target: gateway, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
      "/stream": { target: cdc, changeOrigin: true, ws: true, rewrite: (p) => p.replace(/^\/stream/, "") },
    },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
});
