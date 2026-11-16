import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 서버와 마찬가지로 이 컴퓨터(127.0.0.1)에서만 연다.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8765", ws: true } },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
});
