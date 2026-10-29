const { test, expect } = require('@playwright/test');
const { startSupplyProductionServer } = require('./fixtures/supply-production-entry.cjs');
let server;
test.beforeAll(async () => { server = await startSupplyProductionServer(); });
test.afterAll(async () => { try { expect(server.unhandled).toEqual([]); } finally { await server.close(); } });

test('production login stylesheet resolves its background image and local assets without 404 responses', async ({ page }) => {
  const failures = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => { if (response.url().startsWith(server.origin) && response.status() >= 400) failures.push({ url: response.url(), status: response.status() }); });
  await page.context().route('**/*', route => new URL(route.request().url()).origin === server.origin ? route.continue() : route.abort('blockedbyclient'));
  await page.goto(server.origin + '/#/login');
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible();
  const backgrounds = await page.locator('#hoim *').evaluateAll(nodes => nodes.flatMap(node => {
    const value = getComputedStyle(node).backgroundImage;
    return Array.from(value.matchAll(/url\(["']?([^"')]+)["']?\)/g), match => match[1]);
  }));
  expect(backgrounds.length).toBeGreaterThan(0);
  for (const url of new Set(backgrounds)) {
    expect(new URL(url).origin).toBe(server.origin);
    const response = await page.request.get(url);
    expect(response.status()).toBe(200);
    await page.evaluate(async source => { const image = new Image(); image.src = source; await image.decode(); if (image.naturalWidth <= 0 || image.naturalHeight <= 0) throw Error('Empty background geometry'); }, url);
  }
  expect(failures).toEqual([]);
  expect(errors).toEqual([]);
});
