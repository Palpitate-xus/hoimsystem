const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can view infection control tabs", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/vitalsign/infection`, { waitUntil: "networkidle" });
  await expect(page.getByText("院感监测").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("tab", { name: "感染病例" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "暴发预警" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "消毒监测" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "职业暴露" })).toBeVisible();
});
