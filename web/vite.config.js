import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import yaml from "@modyfi/vite-plugin-yaml";
import vueDevTools from "vite-plugin-vue-devtools";

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
        target: "http://127.0.0.1:8023",
        changeOrigin: true,
      },
    },
  },
});
