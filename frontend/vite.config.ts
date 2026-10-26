import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发期把 /api 代理到后端，避免跨域；生产由 datadict-web 同源托管静态资源。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
