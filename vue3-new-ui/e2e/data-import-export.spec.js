const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can use data import and export page", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/admin/dataImportExport`, { waitUntil: "networkidle" });
  await expect(page.getByText("数据导入导出").first()).toBeVisible({ timeout: 5000 });
  await expect(page.getByText("医生", { exact: true })).toBeVisible();
  await expect(page.getByText("患者", { exact: true })).toBeVisible();
  await expect(page.getByText("药品", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "下载模板" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "导出全部" }).last()).toBeVisible();
});
