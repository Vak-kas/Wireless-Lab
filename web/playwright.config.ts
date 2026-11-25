import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// NRTRAIL_E2E=mock   : 서버 없이 고정 데이터(VITE_API=mock)로 화면만 시험한다.
// NRTRAIL_E2E=server : 화면을 빌드해 실제 로컬 서버(MockEngine)에 붙여 시험한다. (기본)
// NRTRAIL_E2E_URL    : 이미 떠 있는 서버를 대상으로 한다.
const mode = process.env.NRTRAIL_E2E ?? "server";
const external = process.env.NRTRAIL_E2E_URL;
const python =
  process.env.NRTRAIL_PY ?? path.resolve("..", "venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const port = mode === "mock" ? 4173 : 8799;

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: external ?? `http://127.0.0.1:${port}`,
    viewport: { width: 1280, height: 800 },
    // GPU 프로세스를 따로 띄우지 못하는 환경(샌드박스 등)에서는 화면 캡처가 멈춘다. 브라우저 프로세스 안에서 그리게 한다.
    launchOptions: { args: ["--in-process-gpu"] },
  },
  webServer: external
    ? undefined
    : mode === "mock"
      ? {
          // 가짜 데이터로 빌드한 화면은 dist-e2e 에 따로 둔다. web/dist 에 빌드하면 실제 프로그램이 쓰는 화면을 덮어써서,
          // 프로그램을 열었을 때 장비가 하나도 안 보이게 된다(실제로 그렇게 됐었다).
          command: "npx tsc -b && npx vite build --outDir dist-e2e && npx vite preview --outDir dist-e2e --port 4173 --strictPort --host 127.0.0.1",
          url: "http://127.0.0.1:4173",
          reuseExistingServer: false,
          timeout: 120_000,
          env: { VITE_API: "mock", VITE_MOCK_STEP_MS: "40" },
        }
      : {
          command: `npm run build && "${python}" -m nrtrail --port ${port} --engine mock --mock-delay 0.03`,
          url: `http://127.0.0.1:${port}/api/health`,
          reuseExistingServer: false,
          timeout: 120_000,
          // 시험용 세션은 임시 폴더에 둔다(사용자의 sessions/ 를 건드리지 않는다).
          env: { NRTRAIL_SESSIONS: path.join(os.tmpdir(), `nrtrail-e2e-${process.pid}`) },
        },
});
