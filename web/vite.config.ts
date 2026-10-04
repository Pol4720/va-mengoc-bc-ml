import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Relative base: the same build works under GitHub Pages (/<repo>/) and from a local folder.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["src/test/setup.ts"],
  },
});
