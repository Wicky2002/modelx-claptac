import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const state = mkdtempSync(join(tmpdir(), "atlas-console-"));
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:8765",
    viewport: { width: 1600, height: 1000 },
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
      args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
  webServer: {
    command: `${process.env.ATLAS_PYTHON ?? "python"} -m uvicorn atlas.api.main:app --host 127.0.0.1 --port 8765`,
    cwd: "..",
    url: "http://127.0.0.1:8765/health",
    timeout: 60000,
    env: {
      DATABASE_URL: `sqlite:///${join(state, "qa.db")}`,
      ATLAS_LLM_SETTINGS_PATH: join(state, "llm.json"),
      LLM_PROVIDER: "none", MQTT_ENABLED: "false", ATLAS_AUTH: "", ATLAS_TOKENS: "",
      ATLAS_OPERATOR_TOKEN: "",
    },
  },
});
