import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// El proxy evita CORS: la UI llama a /api y Vite lo reenvía a la API de revisión.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8100" },
  },
});
