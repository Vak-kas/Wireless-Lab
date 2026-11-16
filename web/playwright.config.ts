import { defineConfig } from "@playwright/test";

// 기본: 서버 없이 고정 데이터(VITE_API=mock)로 화면만 띄워 종단 시험을 한다.
// NRTRAIL_E2E_URL 이 있으면 이미 떠 있는 서버(예: http://127.0.0.1:8765)를 대상으로 한다.
const external = process.env.NRTRAIL_E2E_URL;

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: external ?? "http://127.0.0.1:4173",
    viewport: { width: 1280, height: 800 },
    // GPU 프로세스를 따로 띄우지 못하는 환경(샌드박스 등)에서는 화면 캡처가 멈춘다. 브라우저 프로세스 안에서 그리게 한다.
    launchOptions: { args: ["--in-process-gpu"] },
  },
  webServer: external
    ? undefined
    : {
        command: "npm run build && npm run preview",
        url: "http://127.0.0.1:4173",
        reuseExistingServer: false,
        timeout: 120_000,
        env: { VITE_API: "mock", VITE_MOCK_STEP_MS: "40" },
      },
});
