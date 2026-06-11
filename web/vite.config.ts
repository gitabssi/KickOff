import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "../gateway/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
