const { test, expect } = require('@playwright/test');
const { beforeSourceHarness } = require('./fixtures/source-harness-setup.cjs');
const { startChartRenderingHarness } = require('./fixtures/chart-rendering-harness.cjs');
let harness;
beforeSourceHarness(test, async () => { harness = await startChartRenderingHarness(); });
test.afterAll(async () => { await harness?.close(); });
async function open(page, screen) {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.context().route('**/*', route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort());
  await page.route('**/api/**', route => route.fulfill({ json: { code: 200, data: route.request().url().includes('/summary') ? { total: 2, failed: 0, pass_rate: 100 } : [{ qc_name: 'synthetic', target_value: 100, measured_value: 101 }, { qc_name: 'synthetic', target_value: 100, measured_value: 99 }] } }));
  await page.goto(harness.origin);
  await page.waitForFunction(() => !!window.__chartProbe);
  await page.evaluate(value => { window.__chartProbe.scope.screen = value; }, screen);
  if (screen === 'campaign') await page.getByRole('button', { name: '查看', exact: true }).first().click();
  return errors;
}
for (const [screen, count, seriesTypes] of [
  ['gallery', 4, ['bar', 'line', 'pie', 'line']],
  ['statistics', 4, ['line', 'line', 'bar', 'bar', 'pie', 'pie']],
  ['campaign', 2, ['line', 'line']],
  ['labqc', 1, ['line', 'line']],
]) {
  test(`${screen} renders its original chart families and disposes every instance on unmount`, async ({ page }) => {
    const errors = await open(page, screen);
    await expect.poll(() => page.evaluate(() => window.__chartProbe.instances().length)).toBe(count);
    await expect.poll(() => page.evaluate(() => Array.from(document.querySelectorAll('canvas')).filter(canvas => { const image = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data; for (let i = 3; i < image.length; i += 4) if (image[i]) return true; return false; }).length)).toBe(count);
    const actual = await page.evaluate(() => window.__chartProbe.instances().flatMap(chart => chart.getOption().series.map(item => item.type)));
    expect(actual).toEqual(seriesTypes);
    if (screen === 'gallery' || screen === 'statistics' || screen === 'labqc') {
      const selected = await page.evaluate(() => { const chart = window.__chartProbe.instances().find(item => item.getOption().legend?.length); const name = chart.getOption().legend[0].data?.[0] ?? chart.getOption().series[0].data[0].name; const key = typeof name === 'string' ? name : name.name; chart.dispatchAction({ type: 'legendToggleSelect', name: key }); return chart.getOption().legend[0].selected[key]; });
      expect(selected).toBe(false);
    }
    await page.evaluate(() => { const probe = window.__chartProbe; probe.retired = probe.instances(); probe.scope.mounted = false; });
    await expect(page.getByText('已卸载', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => window.__chartProbe.retired.every(chart => chart.isDisposed()))).toBe(true);
    expect(errors).toEqual([]);
  });
}
