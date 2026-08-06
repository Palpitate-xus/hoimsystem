const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can view antibiotic management tabs", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/pharmacy/antibiotic`, { waitUntil: "networkidle" });
  await expect(page.getByText("抗菌药物管理").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("tab", { name: "分级目录" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "越级审批" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "使用统计" })).toBeVisible();
});
