const { test, expect } = require("@playwright/test");

const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:8091";

test.describe("登录流程", () => {
  test("管理员登录成功", async ({ page }) => {
    await page.goto(`${BASE_URL}/#/login`);
    await page.fill('input[placeholder="请输入用户名"]', "admin");
    await page.fill('input[placeholder="请输入密码"]', "123456");
    await page.click('button:has-text("登录")');
    await page.waitForURL("**/index", { timeout: 10000 });
    await expect(page.locator("text=首页")).toBeVisible();
  });

  test("登录失败显示错误提示", async ({ page }) => {
    await page.goto(`${BASE_URL}/#/login`);
    await page.fill('input[placeholder="请输入用户名"]', "admin");
    await page.fill('input[placeholder="请输入密码"]', "wrongpassword");
    await page.click('button:has-text("登录")');
    await expect(page.locator(".el-message--error")).toBeVisible({ timeout: 5000 });
  });
});

test.describe("挂号流程", () => {
  test("患者预约挂号", async ({ page }) => {
    // 登录患者账号
    await page.goto(`${BASE_URL}/#/login`);
    await page.fill('input[placeholder="请输入用户名"]', "patient1");
    await page.fill('input[placeholder="请输入密码"]', "123456");
    await page.click('button:has-text("登录")');
    await page.waitForURL("**/index", { timeout: 10000 });

    // 进入预约挂号页面
    await page.click("text=预约挂号");
    await page.waitForURL("**/appointment", { timeout: 5000 });

    // 点击预约挂号按钮
    await page.click('button:has-text("预约挂号")');
    await expect(page.locator("text=选择号源")).toBeVisible();
  });
});
