import { fileURLToPath, URL } from "node:url";
import process from "node:process";

import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import yaml from "@modyfi/vite-plugin-yaml";
import vueDevTools from "vite-plugin-vue-devtools";

const backendTarget = process.env.TAO_DEV_PROXY_TARGET || "http://127.0.0.1:8023";

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), yaml(), vueDevTools()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 18023,
    open: true,
    proxy: {
      "/svr": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
});
