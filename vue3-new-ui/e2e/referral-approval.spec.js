const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

async function login(page) {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1500);
}

test("admin can use referral and MDT approval page", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/#/doctor/referralApproval`, { waitUntil: "networkidle" });
  await expect(page.getByText("转诊/会诊审批").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByRole("tab", { name: "转诊申请" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "会诊申请" })).toBeVisible();
  await expect(page.locator(".el-table").first()).toBeVisible();
  await page.getByRole("tab", { name: "会诊申请" }).click();
  await expect(page.locator(".el-table").last()).toBeVisible();
});
