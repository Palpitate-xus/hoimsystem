const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can open drug damage page", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/pharmacy/drugDamage`, { waitUntil: "networkidle" });
  await expect(page.getByText("药品报损").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("button", { name: "提交报损" })).toBeVisible();
});
