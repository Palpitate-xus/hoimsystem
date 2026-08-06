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

test("admin can view department statistics", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/#/report/reports`, { waitUntil: "networkidle" });
  await page.getByText("科室统计", { exact: true }).click();
  const activePane = page.getByRole("tabpanel", { name: "科室统计" });
  await expect(activePane.getByText("接诊人数").first()).toBeVisible({ timeout: 5000 });
  await expect(activePane.getByText("已收收入").first()).toBeVisible({ timeout: 5000 });
  await page.getByRole("button", { name: "查询" }).last().click();
  await expect(activePane.locator(".el-table")).toBeVisible({ timeout: 5000 });
});
