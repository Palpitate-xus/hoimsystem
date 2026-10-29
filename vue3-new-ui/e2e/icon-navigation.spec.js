const { test, expect } = require('@playwright/test');
const { startSupplyProductionServer } = require('./fixtures/supply-production-entry.cjs');

let server;
const token = 'synthetic-icon-navigation-read-only';
const topIcons = {
  'AI 平台': 'Cpu',
  '首页': 'House',
  '管理员模块': 'Management',
  '医生工作站': 'FirstAidKit',
  '药房管理': 'Box',
  '收费管理': 'Wallet',
  '排队叫号': 'Bell',
  '报到签到': 'CircleCheck',
  '护士预检': 'Odometer',
  '物资设备': 'Tools',
  '检验科': 'Collection',
  '复诊随访': 'ChatDotRound',
  '报表统计': 'DataAnalysis',
  '系统管理': 'Setting',
  '住院管理': 'OfficeBuilding',
  '体检管理': 'DocumentChecked',
};
const homeData = {
  '/api/notice/getList': [{ title: '图标验证公告', content: '只读合成首页数据', sendtime: '2026-10-29T08:00:00', isemergency: false }],
  '/api/chargeManagement/getList': [{ status: 1, amount: '12.50' }],
  '/api/prescriptionManagement/getList': [{ status: 0 }],
  '/api/appointmentManagement/getList': [{ id: 101 }],
  '/api/registrationManagement/getList': [{ id: 102 }],
};

test.beforeAll(async () => { server = await startSupplyProductionServer(); });
test.afterAll(async ({}, info) => {
  try { expect(server.unhandled).toEqual([]); }
  finally {
    await server.close();
    await info.attach('production-icon-server-cleanup', {
      body: JSON.stringify({ origin: server.origin, closed: !server.listening, unhandled: server.unhandled, dist_manifest: server.manifest }),
      contentType: 'application/json',
    });
  }
});

async function openHome(page, { layout } = {}) {
  const state = { errors: [], unexpected: [], bootstrap: [], reads: [] };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(({ value, layout }) => {
    localStorage.clear();
    localStorage.setItem('hoim-token', value);
    if (layout) localStorage.setItem('hoim-theme', JSON.stringify({ layout }));
  }, { value: token, layout });
  await page.context().route('**/*', route => new URL(route.request().url()).origin === server.origin ? route.continue() : route.abort('blockedbyclient'));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    if (path === '/api/userInfo' && method === 'POST') {
      state.bootstrap.push({ method, path, body: request.postDataJSON() });
      return route.fulfill({ json: { code: 200, data: { username: '合成图标只读管理员', permissions: ['super_admin', 'admin'], avatar: '' } } });
    }
    if (path === '/api/events/stream' && method === 'GET') return route.fulfill({ status: 204, body: '' });
    if (method === 'GET' && Object.hasOwn(homeData, path)) {
      state.reads.push(path);
      return route.fulfill({ json: { code: 200, data: homeData[path] } });
    }
    state.unexpected.push({ method, path });
    return route.abort('blockedbyclient');
  });
  await page.goto(server.origin + '/#/index');
  await expect(page.locator('.index-container .stat-card')).toHaveCount(4);
  await expect(page.locator('.index-container')).toContainText('¥12.50');
  await expect.poll(() => state.reads.length).toBe(5);
  return state;
}

function checked(state) {
  expect(state.errors).toEqual([]);
  expect(state.unexpected).toEqual([]);
  expect(state.bootstrap).toEqual([{ method: 'POST', path: '/api/userInfo', body: { accesstoken: token } }]);
}

async function assertDrawn(svg, { minimum = 10, maximum = 40 } = {}) {
  await expect(svg).toBeVisible();
  await expect.poll(() => svg.evaluate(element => {
    const rect = element.getBoundingClientRect(), shape = element.getBBox();
    return { namespace: element.namespaceURI, width: rect.width, height: rect.height, drawn: shape.width > 0 && shape.height > 0 };
  })).toEqual({ namespace: 'http://www.w3.org/2000/svg', width: expect.any(Number), height: expect.any(Number), drawn: true });
  const size = await svg.boundingBox();
  expect(size.width).toBeGreaterThanOrEqual(minimum);
  expect(size.height).toBeGreaterThanOrEqual(minimum);
  expect(size.width).toBeLessThanOrEqual(maximum);
  expect(size.height).toBeLessThanOrEqual(maximum);
}

async function assertNoUnresolvedIcons(page) {
  const invalid = await page.locator('.el-icon:visible').evaluateAll(icons => icons.flatMap(icon => {
    const child = icon.firstElementChild;
    return child?.namespaceURI === 'http://www.w3.org/2000/svg' && child.localName === 'svg' ? [] : [icon.outerHTML];
  }));
  expect(invalid).toEqual([]);
}

test('生产超级管理员侧栏逐项显示业务图标，展开后的叶子项和首页卡片均绘制真实 SVG', async ({ page }) => {
  const state = await openHome(page);
  const menu = page.locator('.side-container .el-menu').first();
  const entries = menu.locator(':scope > .el-menu-item, :scope > .el-sub-menu > .el-sub-menu__title');
  await expect(entries).toHaveCount(Object.keys(topIcons).length);
  const actual = await entries.evaluateAll(nodes => nodes.map(node => ({
    title: node.querySelector('span')?.textContent.trim(),
    href: node.querySelector('.vab-fas-icon svg use')?.getAttribute('href'),
  })));
  expect(actual.map(item => item.title).sort()).toEqual(Object.keys(topIcons).sort());
  for (const item of actual) expect(item.href).toMatch(new RegExp('#icon-' + topIcons[item.title] + '$'));
  expect(new Set(actual.map(item => item.href)).size).toBe(actual.length);
  expect(actual.some(item => /#icon-(?:More|MoreFilled|QuestionFilled)$/.test(item.href))).toBe(false);
  for (let index = 0; index < await entries.count(); index++) {
    await assertDrawn(entries.nth(index).locator('.vab-fas-icon svg'));
  }
  const groups = menu.locator(':scope > .el-sub-menu > .el-sub-menu__title');
  for (let index = 0; index < await groups.count(); index++) {
    const title = groups.nth(index);
    if (!await title.evaluate(node => node.parentElement.classList.contains('is-opened'))) await title.click();
  }
  const leafIcons = menu.locator('.el-menu-item .vab-fas-icon svg');
  expect(await leafIcons.count()).toBeGreaterThan(90);
  for (let index = 0; index < await leafIcons.count(); index++) {
    await assertDrawn(leafIcons.nth(index));
    expect(await leafIcons.nth(index).locator('use').getAttribute('href')).not.toMatch(/#icon-(?:More|MoreFilled|QuestionFilled)$/);
  }
  const cards = page.locator('.index-container .stat-card');
  for (const [index, name] of ['User', 'Document', 'Money', 'Bell'].entries()) {
    const svg = cards.nth(index).locator('.stat-icon svg');
    await assertDrawn(svg, { minimum: 26, maximum: 30 });
    await expect(svg.locator('use')).toHaveAttribute('href', new RegExp('#icon-' + name + '$'));
  }
  await assertNoUnresolvedIcons(page);
  checked(state);
});

test('生产侧栏支持键盘收起展开，收起后首页图标保留且与页签图标一致', async ({ page }) => {
  const state = await openHome(page);
  const home = page.locator(".side-container .el-menu").first().locator(':scope > .el-menu-item:has(.vab-fas-icon use[href$="#icon-House"])');
  const tab = page.getByRole('tab', { name: '首页', exact: true });
  await assertDrawn(home.locator('.vab-fas-icon svg'));
  await assertDrawn(tab.locator('.tab-icon svg'));
  const href = await home.locator('svg use').getAttribute('href');
  await expect(tab.locator('.tab-icon svg use')).toHaveAttribute('href', href);
  const collapse = page.getByRole('button', { name: '收起菜单', exact: true });
  await expect(collapse).toHaveAttribute('aria-expanded', 'true');
  await expect(collapse.locator('svg use')).toHaveAttribute('href', /#icon-DArrowLeft$/);
  await collapse.focus();
  await page.keyboard.press('Enter');
  const expand = page.getByRole('button', { name: '展开菜单', exact: true });
  await expect(expand).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('.side-container')).toHaveClass(/is-collapse/);
  await expect(expand.locator('svg use')).toHaveAttribute('href', /#icon-DArrowRight$/);
  await assertDrawn(expand.locator('svg'), { minimum: 18, maximum: 24 });
  await assertDrawn(home.locator('.vab-fas-icon svg'));
  await expect(home.locator('svg use')).toHaveAttribute('href', href);
  await expand.focus();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: '收起菜单', exact: true })).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.side-container')).not.toHaveClass(/is-collapse/);
  await assertDrawn(home.locator('.vab-fas-icon svg'));
  await assertNoUnresolvedIcons(page);
  checked(state);
});

test('生产导航工具保留约 20px 的真实图标，键盘可打开主题和全屏并刷新首页', async ({ page }) => {
  const state = await openHome(page);
  const tools = { '收起菜单': 'DArrowLeft', '刷新页面': 'Refresh', '主题配置': 'Brush', '进入全屏': 'FullScreen' };
  for (const [label, name] of Object.entries(tools)) {
    const button = page.getByRole('button', { name: label, exact: true });
    await assertDrawn(button.locator('svg'), { minimum: 18, maximum: 24 });
    await expect(button.locator('svg use')).toHaveAttribute('href', new RegExp('#icon-' + name + '$'));
  }
  await page.getByRole('button', { name: '主题配置', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog', { name: '主题配置', exact: true })).toBeVisible();
  await assertNoUnresolvedIcons(page);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: '主题配置', exact: true })).toBeHidden();
  await page.getByRole('button', { name: '进入全屏', exact: true }).focus();
  await page.keyboard.press('Enter');
  const leave = page.getByRole('button', { name: '退出全屏', exact: true });
  await expect(leave).toBeVisible();
  await expect(leave.locator('svg use')).toHaveAttribute('href', /#icon-ScaleToOriginal$/);
  await assertDrawn(leave.locator('svg'), { minimum: 18, maximum: 24 });
  await leave.focus();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: '进入全屏', exact: true })).toBeVisible();
  const beforeRefresh = state.reads.filter(path => path === '/api/notice/getList').length;
  await page.getByRole('button', { name: '刷新页面', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect.poll(() => state.reads.filter(path => path === '/api/notice/getList').length).toBeGreaterThan(beforeRefresh);
  await expect(page.locator('.index-container')).toContainText('¥12.50');
  await assertNoUnresolvedIcons(page);
  checked(state);
});

test('生产横向布局菜单与工具图标实际绘制，20px 工具在深色背景保持清楚可见', async ({ page }) => {
  const state = await openHome(page, { layout: 'horizontal' });
  const top = page.locator('.top-container');
  await expect(top).toBeVisible();
  await expect(page.locator('.side-container')).toHaveCount(0);
  const menuIcons = top.locator('.el-menu .vab-fas-icon svg:visible');
  expect(await menuIcons.count()).toBeGreaterThan(0);
  for (let index = 0; index < await menuIcons.count(); index++) {
    const svg = menuIcons.nth(index);
    await assertDrawn(svg);
    expect(await svg.locator('use').getAttribute('href')).not.toMatch(/#icon-(?:More|MoreFilled|QuestionFilled)$/);
  }
  for (const [label, name] of Object.entries({ '进入全屏': 'FullScreen', '主题配置': 'Brush', '刷新页面': 'Refresh' })) {
    const button = top.getByRole('button', { name: label, exact: true });
    await expect(button).toHaveClass(/nav-icon/);
    const svg = button.locator('svg');
    await assertDrawn(svg, { minimum: 18, maximum: 24 });
    await expect(svg.locator('use')).toHaveAttribute('href', new RegExp('#icon-' + name + '$'));
    const contrast = await svg.evaluate(element => {
      const read = color => color.match(/[\d.]+/g).map(Number);
      const foreground = read(getComputedStyle(element).color);
      const background = read(getComputedStyle(element.closest('.top-container')).backgroundColor);
      const alpha = foreground[3] ?? 1;
      const composite = foreground.slice(0, 3).map((value, index) => value * alpha + background[index] * (1 - alpha));
      const luminance = values => values.slice(0, 3).map(value => {
        const channel = value / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
      const light = luminance(composite), dark = luminance(background);
      return { ratio: (Math.max(light, dark) + 0.05) / (Math.min(light, dark) + 0.05), background: background.slice(0, 3) };
    });
    expect(contrast.background.every(channel => channel < 80)).toBe(true);
    expect(contrast.ratio).toBeGreaterThanOrEqual(4.5);
  }
  await assertNoUnresolvedIcons(page);
  checked(state);
});
