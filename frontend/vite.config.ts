import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // File watching through Docker bind mounts is unreliable on some systems, so poll.
    watch: { usePolling: true },
  },
});
