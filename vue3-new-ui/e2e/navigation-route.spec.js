const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("patient can view navigation route controls", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "patient1");
  await page.fill('input[type="password"]', "123456");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/patient/navigation`, { waitUntil: "networkidle" });
  await expect(page.getByText("院内路线指引", { exact: true })).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("combobox").nth(0)).toBeVisible();
  await expect(page.getByRole("combobox").nth(1)).toBeVisible();
});
