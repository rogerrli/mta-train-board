import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The Python server (app/server.py) serves the built board from frontend/dist at
// the site root ("/"), same-origin with the /api/* routes. During `npm run dev`,
// Vite proxies /api to the running uvicorn server so the board sees live data.
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
