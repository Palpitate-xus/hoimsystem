const { test, expect } = require('@playwright/test');
const { startRequestHarness } = require('../scripts/request-regression-harness.cjs');
let harness;
const token = 'synthetic-stream-access-token';
test.beforeAll(async () => { harness = await startRequestHarness(); });
test.afterAll(async () => { await harness?.close(); });
test.beforeEach(async ({ page }) => {
  harness.clear();
  await page.context().route('**/*', route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort());
  await page.goto(harness.origin);
  await page.waitForFunction(() => !!window.__requestRegression);
  await page.evaluate(value => { window.__requestRegression.state.user.accessToken = value; }, token);
});
test('an actual Fetch stream 403 stops and notifies one permission recheck while preserving the session', async ({ page }) => {
  await page.evaluate(value => {
    const { request, eventBus, clinicalEventStream } = window.__requestRegression;
    eventBus.on('access-denied', event => { if (event?.source === 'clinical-event-stream') window.__streamRefresh = request({ url: '/access/me' }); });
    clinicalEventStream.start(value);
  }, token);
  await expect.poll(() => page.evaluate(() => window.__requestRegression.effects.accessDenied.length)).toBe(1);
  await page.evaluate(() => window.__streamRefresh);
  const state = await page.evaluate(() => { const { effects, state, clinicalEventStream } = window.__requestRegression; return { events: effects.accessDenied, token: state.user.accessToken, dispatches: effects.dispatches, routes: effects.routes, stopped: clinicalEventStream.token === '', timer: clinicalEventStream.retryTimer }; });
  expect(state).toEqual({ events: [{ token, status: 403, source: 'clinical-event-stream' }], token, dispatches: [], routes: [], stopped: true, timer: null });
  expect(harness.count('GET', '/api/events/stream')).toBe(1);
  expect(harness.count('GET', '/api/access/me')).toBe(1);
  expect(harness.requests.every(request => request.token === token)).toBe(true);
});
test('an actual Fetch stream 401 reaches the existing authenticated-request expiry handling', async ({ page }) => {
  harness.setStreamStatus(401);
  await page.evaluate(value => {
    const { request, eventBus, clinicalEventStream } = window.__requestRegression;
    eventBus.on('access-denied', event => { if (event?.source === 'clinical-event-stream') window.__streamRefresh = request({ url: '/unauthorized' }).catch(error => error.response.status); });
    clinicalEventStream.start(value);
  }, token);
  await expect.poll(() => page.evaluate(() => window.__requestRegression.effects.accessDenied.length)).toBe(1);
  expect(await page.evaluate(() => window.__streamRefresh)).toBe(401);
  const state = await page.evaluate(() => { const { effects, state, clinicalEventStream } = window.__requestRegression; return { token: state.user.accessToken, dispatches: effects.dispatches, routes: effects.routes, stopped: clinicalEventStream.token === '', timer: clinicalEventStream.retryTimer }; });
  expect(state).toEqual({ token: '', dispatches: ['user/resetAccessToken'], routes: [{ path: '/login' }], stopped: true, timer: null });
  expect(harness.count('GET', '/api/events/stream')).toBe(1);
  expect(harness.count('GET', '/api/unauthorized')).toBe(1);
});
