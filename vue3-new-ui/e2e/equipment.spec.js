const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can view equipment management tabs", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/equipment/index`, { waitUntil: "networkidle" });
  await expect(page.getByRole("button", { name: "新增设备" })).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("tab", { name: "设备台账" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "维修记录" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "保养记录" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "耗材追溯" })).toBeVisible();
});
