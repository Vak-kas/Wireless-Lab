import { expect, test } from "@playwright/test";

test("앱이 열린다", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "nrtrail" })).toBeVisible();
});
