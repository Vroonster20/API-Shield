import { defineConfig } from "vite";
export default defineConfig({
  build: { outDir: "dist" },
  server: {
    host: "127.0.0.1",
    proxy: {
      "/admin/v1": {
        target: "http://admin.localhost:8081",
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (request) =>
            request.setHeader("Origin", "http://admin.localhost:8081"),
          );
        },
      },
    },
  },
});
