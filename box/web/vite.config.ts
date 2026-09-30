import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8080", ws: true },
      "/mcp": { target: "http://localhost:8080" },
    },
  },
  test: { environment: "jsdom", exclude: ["e2e/**", "node_modules/**"] },
});
