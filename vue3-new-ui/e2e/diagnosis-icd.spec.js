const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("admin can open diagnosis template and ICD-10 pages", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);

  await page.goto(`${BASE}/#/doctor/diagnosisTemplate`, { waitUntil: "networkidle" });
  await expect(page.getByRole("button", { name: "新建诊断模板" })).toBeVisible({ timeout: 5000 });

  await page.goto(`${BASE}/#/inpatient/icd10`, { waitUntil: "networkidle" });
  await expect(page.getByText("诊断编码", { exact: true })).toBeVisible({ timeout: 5000 });
  await expect(page.getByText("手术操作编码", { exact: true })).toBeVisible();
  await expect(page.getByPlaceholder("按编码、名称或分类搜索")).toBeVisible();
});
