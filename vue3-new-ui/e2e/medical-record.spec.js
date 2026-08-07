const { test, expect } = require("@playwright/test");

const BASE = process.env.E2E_BASE_URL || "http://localhost:8091";

test("医生可以看到病历状态并完成签名", async ({ page }) => {
  let listRequestCount = 0;
  await page.route("**/api/medicalRecord/getList**", async (route) => {
    listRequestCount += 1;
    const signed = listRequestCount > 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        code: 200,
        msg: "success",
        data: [{
          uuid: "e2e-medical-record",
          consultation_time: "2026-08-07 09:00:00",
          patient_name: "测试患者",
          symptom: "发热",
          result: "上呼吸道感染",
          status: signed ? 1 : 0,
          status_text: signed ? "已签名" : "草稿",
        }],
      }),
    });
  });
  await page.route("**/api/medicalRecord/sign", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success" }) });
  });
  await page.route("**/api/userInfo", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ code: 200, msg: "success", data: { username: "admin", permissions: ["admin"], avatar: "" } }),
    });
  });
  await page.addInitScript(() => localStorage.setItem("hoim-token", "e2e-token"));

  await page.goto(`${BASE}/#/doctor/medicalRecord`, { waitUntil: "networkidle" });

  await expect(page.getByText("草稿").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "签名" })).toBeVisible();
  // 本地 dev server 的 overlay 可能残留上一轮编译提示，不属于业务页面。
  await page.locator("#rspack-dev-server-client-overlay").evaluate((element) => element.remove()).catch(() => {});
  await page.getByRole("button", { name: "签名" }).click();
  await page.getByRole("button", { name: "确定" }).click();
  await expect(page.getByText("已签名").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "编辑" })).toHaveCount(0);
});
