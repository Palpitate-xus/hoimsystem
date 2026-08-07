const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can open sample tracking workflow", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/lab/labResult`, { waitUntil: "networkidle" });
  await expect(page.getByRole("tab", { name: "检查结果录入" })).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("tab", { name: "待处理申请" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "检查结果", exact: true })).toBeVisible();
});
