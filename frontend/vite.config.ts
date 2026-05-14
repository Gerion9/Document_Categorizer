import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const rootDir = dirname(fileURLToPath(import.meta.url));
const envDir = resolve(rootDir, "..");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, envDir, "");
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react()],
    envDir,
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
          timeout: 1_800_000,
          proxyTimeout: 1_800_000,
        },
      },
    },
  };
});
