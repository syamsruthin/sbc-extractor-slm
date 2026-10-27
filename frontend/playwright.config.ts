import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// E2E runs against an isolated backend (fresh SQLite, fake LLM) on :8001 and a Vite dev server on :5174.
const varDir = process.env.E2E_VAR_DIR ?? mkdtempSync(join(tmpdir(), "sbcx-e2e-"));

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5174", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv --directory ../backend run uvicorn sbcx.main:app --port 8001",
      url: "http://127.0.0.1:8001/api/v1/health",
      env: { SBCX_VAR_DIR: varDir, SBCX_LLM_MODE: process.env.E2E_LLM_MODE ?? "fake", SBCX_LOG_LEVEL: "WARNING" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npx vite --port 5174 --strictPort --host 127.0.0.1",
      url: "http://127.0.0.1:5174",
      env: { VITE_BACKEND_URL: "http://127.0.0.1:8001" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
