const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can view imaging workflow tabs", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/lab/imaging`, { waitUntil: "networkidle" });
  await expect(page.getByText("影像检查").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("tab", { name: "检查申请" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "报告书写" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "报告模板" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建影像申请" })).toBeVisible();
});
