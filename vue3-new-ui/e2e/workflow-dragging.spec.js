const { test, expect } = require('@playwright/test');
const { beforeSourceHarness } = require('./fixtures/source-harness-setup.cjs');
const { startWorkflowHarness } = require('./fixtures/workflow-harness.cjs');
let harness;
test.use({ viewport: { width: 1440, height: 1800 } });
beforeSourceHarness(test, async () => { harness = await startWorkflowHarness(); });
test.afterAll(async () => harness?.close());

async function open(page) {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.context().route('**/*', route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort());
  await page.goto(harness.origin);
  await expect(page.getByRole('tabpanel', { name: '所有工作流', exact: true }).getByText('请假申请', { exact: true })).toBeVisible();
  return errors;
}

test('Vue 3 workflow nodes render, reorder by their handle and retain the order after saving', async ({ page }) => {
  const errors = await open(page);
  await page.getByRole('button', { name: '编辑', exact: true }).first().click();
  const dialog = page.getByRole('dialog', { name: '编辑工作流', exact: true });
  const nodes = dialog.locator('.node-item');
  await expect(nodes).toHaveCount(3);
  const before = await nodes.locator('input[placeholder="节点名称"]').evaluateAll(inputs => inputs.map(input => input.value));
  expect(before).toEqual(['提交申请', '直属上级审批', '人事审批']);
  // Sortable uses actual pointer movement; neither component state nor DOM order is patched.
  const first = await nodes.first().locator('.node-handle').boundingBox();
  const last = await nodes.last().boundingBox();
  expect(last.y + last.height).toBeLessThan(page.viewportSize().height);
  await page.mouse.move(first.x + first.width / 2, first.y + first.height / 2);
  await page.mouse.down();
  await page.mouse.move(first.x + first.width / 2, last.y + last.height - 5, { steps: 18 });
  // Native HTML dragover updates can follow the first DOM insertion asynchronously.
  await expect(nodes.nth(1)).toHaveClass(/sortable-chosen/);
  await page.mouse.move(first.x + first.width / 2 + 4, last.y + last.height - 8, { steps: 3 });
  await expect.poll(() => nodes.locator('input[placeholder="节点名称"]').evaluateAll(inputs => inputs.map(input => input.value))).toEqual(['直属上级审批', '人事审批', '提交申请']);
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => window.__workflowProbe.workflowForm.nodes.map(node => node.name))).toEqual(['直属上级审批', '人事审批', '提交申请']);
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: '编辑', exact: true }).first().click();
  await expect.poll(() => nodes.locator('input[placeholder="节点名称"]').evaluateAll(inputs => inputs.map(input => input.value))).toEqual(['直属上级审批', '人事审批', '提交申请']);
  expect(errors).toEqual([]);
  expect(harness.unhandled).toEqual([]);
});

test('Vue 3 workflow nodes can be added and deleted while keeping at least one node', async ({ page }) => {
  const errors = await open(page);
  await page.getByRole('button', { name: '创建工作流', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '创建工作流', exact: true });
  const nodes = dialog.locator('.node-item');
  await expect(nodes).toHaveCount(1);
  await dialog.getByRole('button', { name: '添加节点', exact: true }).click();
  await expect(nodes).toHaveCount(2);
  const input = nodes.last().getByPlaceholder('节点名称', { exact: true });
  await input.fill('升级后新增节点');
  await nodes.first().locator('.node-actions button').click();
  await expect(nodes).toHaveCount(1);
  await expect(nodes.getByPlaceholder('节点名称', { exact: true })).toHaveValue('升级后新增节点');
  await nodes.first().locator('.node-actions button').click();
  await expect(page.getByText('至少需要保留一个节点', { exact: true })).toBeVisible();
  await expect(nodes).toHaveCount(1);
  expect(errors).toEqual([]);
  expect(harness.unhandled).toEqual([]);
});
