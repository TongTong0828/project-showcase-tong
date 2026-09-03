import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  use: {
    baseURL: "http://127.0.0.1:3090",
  },
  webServer: {
    command: "VITE_WORKBENCH_FIXTURES=1 pnpm dev",
    url: "http://127.0.0.1:3090",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
