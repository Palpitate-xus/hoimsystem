const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can open doctor lab order page", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/doctor/labOrder`, { waitUntil: "networkidle" });
  await expect(page.getByText("检查检验申请").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("button", { name: "新增申请" })).toBeVisible();
});
