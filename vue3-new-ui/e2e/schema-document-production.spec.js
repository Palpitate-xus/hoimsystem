const {test, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');
const {startServer, setup, checked} = require('./fixtures/drug-label-production-entry.cjs');
let server;
test.beforeAll(async () => {server = await startServer();});
test.afterAll(async () => {try {expect(server.unhandled).toEqual([]);} finally {await server.close();}});

test('canonical business page uses one inert complete schema registry with independent browser SHA checks', async ({page}) => {
  const state = await setup(page, server);
  const nodes = page.locator('script#hoim-schema-data[type="application/json"]');
  await expect(nodes).toHaveCount(1);
  const values = await nodes.evaluate(async node => {
    const value = JSON.parse(node.textContent);
    if (value.schema_version !== 'hoim_static_schema_document_v1') throw new Error('Wrong generated schema document');
    return Promise.all(Object.entries(value.entries).map(async ([sha, entry]) => {
      const bytes = Uint8Array.from(atob(entry.encoded), char => char.charCodeAt(0));
      const actual = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), byte => byte.toString(16).padStart(2, '0')).join('');
      return {valid: actual === sha && bytes.length === entry.packedBytes, byteLength: entry.byteLength};
    }));
  });
  expect(values.length).toBeGreaterThan(20);
  expect(values.every(value => value.valid && value.byteLength > 0 && value.byteLength <= 262144)).toBe(true);
  expect(state.calls.filter(call => call.path.startsWith('/api/ai/drug-label-sources'))).toEqual([]);
  checked(state);
});

test('damaged complete schema data stops the canonical business module before any AI source request', async ({page}) => {
  const html = fs.readFileSync(path.resolve(__dirname, '../dist/index.html'), 'utf8');
  const pattern = /(<script id="hoim-schema-data" type="application\/json">)([^<]+)(<\/script>)/;
  const match = html.match(pattern);
  expect(match).not.toBeNull();
  const value = JSON.parse(match[2]);
  for (const entry of Object.values(value.entries)) {
    const bytes = Buffer.from(entry.encoded, 'base64');
    bytes[bytes.length - 1] ^= 1;
    entry.encoded = bytes.toString('base64');
  }
  const changed = html.replace(pattern, (_, start, body, end) => start + JSON.stringify(value) + end);
  const errors = [], calls = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => {if (message.type() === 'error') errors.push(message.text());});
  await page.addInitScript(() => localStorage.setItem('hoim-token', 'synthetic-static-contract-corruption'));
  await page.context().route('**/*', route => new URL(route.request().url()).origin === server.origin ? route.continue() : route.abort('blockedbyclient'));
  await page.route(server.origin + '/', route => route.fulfill({status: 200, contentType: 'text/html', body: changed}));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    calls.push(url.pathname);
    if (url.pathname === '/api/events/stream') return route.fulfill({status: 200, contentType: 'text/event-stream', body: ': synthetic idle\n\n'});
    if (url.pathname === '/api/userInfo') return route.fulfill({json: {code: 200, data: {username: 'synthetic-corrupted-static-contract', permissions: ['pharmacist'], avatar: ''}}});
    return route.fulfill({status: 599, json: {detail: 'No unexpected synthetic fallback'}});
  });
  await page.goto(server.origin + '/#/pharmacy/pharmaceutical');
  await expect.poll(() => errors.some(error => error.includes('Generated static schema SHA differs'))).toBe(true);
  expect(calls.filter(url => url.startsWith('/api/ai/'))).toEqual([]);
  await expect(page.getByRole('button', {name: '核对说明书字段', exact: true})).toHaveCount(0);
});
