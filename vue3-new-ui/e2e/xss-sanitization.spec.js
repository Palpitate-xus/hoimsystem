const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("rich text preview removes executable HTML", async ({ page }) => {
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.goto(`${BASE}/#/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="text"]', "admin");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(1200);
  await page.goto(`${BASE}/#/system/editor`, { waitUntil: "networkidle" });
  const editor = page.locator("textarea").first();
  await editor.fill('<script>alert(1)</script><img src=x onerror=alert(2)><p>安全文本</p>');
  await expect(page.getByText("安全文本", { exact: true })).toBeVisible();
  await expect(page.locator(".preview-content script")).toHaveCount(0);
  await expect(page.locator(".preview-content img")).toHaveCount(0);
});
