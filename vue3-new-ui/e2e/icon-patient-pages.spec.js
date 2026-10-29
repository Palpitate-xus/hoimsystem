const { test, expect } = require('@playwright/test');
const { startSupplyProductionServer } = require('./fixtures/supply-production-entry.cjs');

let server;
const token = 'synthetic-icon-patient-pages-read-only';

test.beforeAll(async () => { server = await startSupplyProductionServer(); });
test.afterAll(async ({}, info) => {
  try { expect(server.unhandled).toEqual([]); }
  finally {
    await server.close();
    await info.attach('production-patient-icon-server-cleanup', {
      body: JSON.stringify({ origin: server.origin, closed: !server.listening, unhandled: server.unhandled, dist_manifest: server.manifest }),
      contentType: 'application/json',
    });
  }
});

async function session(page, role, data) {
  const state = { errors: [], unexpected: [], reads: [], bootstrap: [] };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(value => {
    localStorage.clear();
    localStorage.setItem('hoim-token', value);
  }, token);
  await page.context().route('**/*', route => new URL(route.request().url()).origin === server.origin ? route.continue() : route.abort('blockedbyclient'));
  await page.route('**/api/**', async route => {
    const request = route.request(), method = request.method(), path = new URL(request.url()).pathname;
    if (path === '/api/userInfo' && method === 'POST') {
      state.bootstrap.push({ method, path, body: request.postDataJSON() });
      return route.fulfill({ json: { code: 200, data: { username: '合成图标只读用户', permissions: role === 'super_admin' ? ['super_admin', 'admin'] : [role], avatar: '' } } });
    }
    if (path === '/api/events/stream' && method === 'GET') return route.fulfill({ status: 204, body: '' });
    if (method === 'GET' && Object.hasOwn(data, path)) {
      state.reads.push(path);
      return route.fulfill({ json: { code: 200, data: data[path] } });
    }
    state.unexpected.push({ method, path });
    return route.abort('blockedbyclient');
  });
  return state;
}

async function checked(state, paths) {
  await expect.poll(() => state.reads.slice().sort()).toEqual(paths.slice().sort());
  expect(state.errors).toEqual([]);
  expect(state.unexpected).toEqual([]);
  expect(state.bootstrap).toEqual([{ method: 'POST', path: '/api/userInfo', body: { accesstoken: token } }]);
}

async function drawnIcon(svg, name) {
  await expect(svg).toBeVisible();
  await expect(svg.locator('use')).toHaveAttribute('href', new RegExp('#icon-' + name + '$'));
  await expect.poll(() => svg.evaluate(element => {
    const rectangle = element.getBoundingClientRect(), drawing = element.getBBox();
    return {
      namespace: element.namespaceURI,
      visible: rectangle.width > 0 && rectangle.height > 0,
      drawn: drawing.width > 0 && drawing.height > 0,
    };
  })).toEqual({ namespace: 'http://www.w3.org/2000/svg', visible: true, drawn: true });
}

test('生产患者导航的科室位置和电话绘制实际 SVG，页面仅调用只读导航 API', async ({ page }) => {
  const data = {
    '/api/navigation/departments': [{ department_id: 201, name: '合成导航科室', location: '合成门诊二楼', phone: '010-00000000', doctors: [] }],
    '/api/navigation/faq': [],
  };
  const state = await session(page, 'patient', data);
  await page.goto(server.origin + '/#/patient/navigation');
  const department = page.locator('.department-card').filter({ hasText: '合成导航科室' });
  await expect(department).toBeVisible();
  await drawnIcon(department.locator('p').filter({ hasText: '合成门诊二楼' }).locator('.el-icon svg'), 'Location');
  await drawnIcon(department.locator('p').filter({ hasText: '010-00000000' }).locator('.el-icon svg'), 'Phone');
  await checked(state, Object.keys(data));
});

test('生产患者导诊标题和查询按钮绘制急救箱与搜索 SVG，未提交导诊请求', async ({ page }) => {
  const data = { '/api/triage/keywords': [] };
  const state = await session(page, 'patient', data);
  await page.goto(server.origin + '/#/patient/triage');
  await drawnIcon(page.getByRole('heading', { name: '请描述您的症状', exact: true }).locator('.el-icon svg'), 'FirstAidKit');
  await drawnIcon(page.getByRole('button', { name: '智能导诊', exact: true }).locator('.el-icon svg'), 'Search');
  await checked(state, Object.keys(data));
});

test('生产超级管理员病区搜索框绘制真实 Search 前缀 SVG，仅读取空病区与科室目录', async ({ page }) => {
  const data = { '/api/ward/getList': [], '/api/departmentManagement/getList': [] };
  const state = await session(page, 'super_admin', data);
  await page.goto(server.origin + '/#/inpatient/wardManagement');
  const search = page.locator('.el-input').filter({ has: page.getByPlaceholder('搜索病区', { exact: true }) });
  await expect(search.getByPlaceholder('搜索病区', { exact: true })).toBeVisible();
  await drawnIcon(search.locator('.el-input__prefix .el-icon svg'), 'Search');
  await checked(state, Object.keys(data));
});
