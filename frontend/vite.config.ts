import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1", port: 5174, strictPort: true,
      proxy: {
        "^/auth(?:/|$)": { target: env.AUTH_PROXY_TARGET || "http://127.0.0.1:8010", changeOrigin: true },
        "^/(?:login|register)(?:[?]|$)": { target: env.AUTH_PROXY_TARGET || "http://127.0.0.1:8010", changeOrigin: true },
        "/assets/auth/": { target: env.AUTH_PROXY_TARGET || "http://127.0.0.1:8010", changeOrigin: true },
        "/api": {
          target: env.API_PROXY_TARGET || "http://127.0.0.1:8001",
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api(?=\/|$)/, ""),
        },
      },
    },
  };
});
