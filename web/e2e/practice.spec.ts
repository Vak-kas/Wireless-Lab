import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SHOTS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots");
// 서버 모드에서는 서버에 아직 없는 기능(추적: M7)을 건너뛴다. 화면 전용(mock) 모드에서는 전부 본다.
const MOCK = process.env.NRTRAIL_E2E === "mock";
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: true });

async function startPractice(page: Page, scenarioTitle?: RegExp) {
  await page.goto("/");
  await expect(page.getByTestId("source-practice")).toBeVisible();
  if (scenarioTitle) await page.getByTestId("source-practice").getByRole("button", { name: scenarioTitle }).click();
  await page.getByTestId("start-practice").click();
  await expect(page.getByTestId("run-scan")).toBeVisible();
}

test("연습 모드: 처음부터 끝까지 (스캔 → SSB → MIB → SIB1 → SIB19 → NTN → 추적)", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("doctor-summary")).toBeVisible();
  await shot(page, "01-start");

  await startPractice(page);
  // 사슬: 스캔만 다음 차례, 나머지는 잠김
  await expect(page.getByTestId("chain-scan")).toHaveAttribute("data-state", "next");
  await expect(page.getByTestId("chain-ssb")).toHaveAttribute("data-state", "locked");

  await page.getByTestId("run-scan").click();
  await expect(page.getByTestId("sticky-bar")).toBeVisible();
  await expect(page.getByTestId("status-scan")).toHaveText("성공");
  await expect(page.getByTestId("figure-spectrum")).toBeVisible();
  await expect(page.getByTestId("chain-scan")).toHaveAttribute("data-state", "done");
  await shot(page, "02-scan");

  await page.getByTestId("follow-cell").click();
  await expect(page.getByTestId("following-cell")).toBeVisible();

  for (const stage of ["ssb", "mib", "sib1", "sib19"]) {
    await expect(page.getByTestId(`chain-${stage}`)).toHaveAttribute("data-state", "next");
    await page.getByTestId("next-stage").click();
    await expect(page.getByTestId(`status-${stage}`)).toHaveText("성공");
    await expect(page.getByTestId(`chain-${stage}`)).toHaveAttribute("data-state", "done");
  }
  await shot(page, "03-follow");

  // 모든 숫자는 출처가 있다: 값 카드의 "어떻게 구했나"가 계산 과정 카드로 이어진다
  const mib = page.locator("#stage-mib");
  await mib.getByRole("button", { name: "어떻게 구했나" }).first().click();
  const derivation = mib.locator(".derivation[data-highlight]");
  await expect(derivation).toBeVisible();
  await expect(derivation.locator(".katex").first()).toBeVisible();
  await mib.screenshot({ path: path.join(SHOTS, "04-mib-derivation.png") });

  // 전문가 정보: SIB1 전체 트리
  await page.getByTestId("fold-expert-sib1").locator("summary").first().click();
  await expect(page.getByTestId("fold-expert-sib1")).toContainText("TS 38");

  // 용어 사전
  await page.locator("#stage-ssb .term").first().hover();
  await expect(page.getByRole("tooltip")).toBeVisible();

  await page.getByTestId("next-stage").click();
  await expect(page.getByTestId("ntn-anomalies")).toBeVisible();
  await expect(page.locator("#ntn-result .figure")).toBeVisible();
  await shot(page, "05-ntn");

  await page.getByRole("link", { name: "추적", exact: true }).click();
  await expect(page.getByTestId("track-toggle")).toBeVisible();
  if (MOCK || process.env.NRTRAIL_E2E_TRACK) {
    await page.getByTestId("track-toggle").click();
    await expect(page.getByTestId("track-csv")).toBeVisible();
    await page.getByTestId("track-toggle").click();
  }
  await shot(page, "06-track");

  await page.getByRole("link", { name: "세션", exact: true }).click();
  await expect(page.getByTestId("sessions-table")).toBeVisible();
  await shot(page, "07-sessions");

  await page.getByRole("link", { name: "설정 · 점검" }).click();
  await expect(page.getByTestId("doctor-table")).toBeVisible();
  await page.getByTestId("settings-save").click();
  await expect(page.getByText("저장했습니다")).toBeVisible();
  await shot(page, "08-settings");
});

test("연습 모드: 실패하면 이유와 해결법을 보여주고 다음 단계는 잠긴 채로 둔다", async ({ page }) => {
  await startPractice(page, /약한/);
  await page.getByTestId("run-scan").click();
  await expect(page.getByTestId("status-scan")).toHaveText("성공");
  await page.getByTestId("follow-cell").click();
  await page.getByTestId("next-stage").click();
  await expect(page.getByTestId("status-ssb")).toHaveText(/성공/);
  await page.getByTestId("next-stage").click();
  await expect(page.getByTestId("status-mib")).toHaveText("실패");
  await expect(page.locator("#stage-mib .diagnostic").first()).toBeVisible();
  await expect(page.locator("#stage-mib .diagnostic button").first()).toBeVisible();
  await expect(page.getByTestId("chain-sib1")).toHaveAttribute("data-state", "locked");
  await page.locator("#stage-mib").screenshot({ path: path.join(SHOTS, "09-failure.png") });
});

test("좁은 화면에서도 가로로 넘치지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await startPractice(page);
  await page.getByTestId("run-scan").click();
  await expect(page.getByTestId("status-scan")).toHaveText("성공");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await shot(page, "10-mobile-scan");
});

test("휴대폰 연동: 휴대폰이 없어도 이유를 알려 주고 화면은 계속 동작한다", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("phone-read").click();
  await expect(page.getByTestId("phone-status").or(page.getByTestId("phone-cells"))).toBeVisible();
  await page.locator("#phone").screenshot({ path: path.join(SHOTS, "11-phone.png") });
});
