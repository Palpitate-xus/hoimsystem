const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can view and run scheduled tasks", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/system/scheduler`, { waitUntil: "networkidle" });
  await expect(page.getByRole("button", { name: "刷新状态" })).toBeVisible({ timeout: 5000 });
  await expect(page.getByText("库存预警检查")).toBeVisible();
  await expect(page.getByText("违约记录统计")).toBeVisible();
  await expect(page.getByText("数据备份", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "立即执行" }).first()).toBeVisible();
});
