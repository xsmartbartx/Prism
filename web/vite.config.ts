import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = process.env.PRISM_BACKEND ?? "http://127.0.0.1:8080";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 800 },
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/s/": backend,
      "/embed/": backend,
      "/healthz": backend,
    },
  },
});
