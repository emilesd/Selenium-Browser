import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react()],
    server: {
      host: env.HOST,
      port: Number(env.PORT),
      proxy: {
        "/api": {
          target: env.VITE_API_BASE_URL_BACKEND || "http://localhost:5000",
          changeOrigin: true,
        },
        "/socket.io": {
          target: env.VITE_API_BASE_URL_BACKEND || "http://localhost:5000",
          changeOrigin: true,
          ws: true,
        },
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
  };
});
