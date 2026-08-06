const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can view insurance control tabs", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/charge/insurance`, { waitUntil: "networkidle" });
  await expect(page.getByText("医保与费用控制").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("tab", { name: "医保目录" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "结算记录" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "慢病登记" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "DRG/DIP 分析" })).toBeVisible();
});
