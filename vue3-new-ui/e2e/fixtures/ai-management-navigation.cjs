const { expect } = require('@playwright/test');

async function managementOptions(page, label) {
  const search = page.getByRole('combobox', { name: '查找管理入口', exact: true });
  await search.fill(label);
  const controls = await search.getAttribute('aria-controls');
  return { search, option: page.locator('[id="' + controls + '"]').getByRole('option', { name: label, exact: true }) };
}

async function selectManagementTab(page, label) {
  const { option } = await managementOptions(page, label);
  await option.click();
}

async function expectManagementEntry(page, label, available) {
  const search = page.getByRole('combobox', { name: '查找管理入口', exact: true });
  if (!available && await search.count() === 0) return;
  const { option } = await managementOptions(page, label);
  if (available) await expect(option).toBeVisible();
  else await expect(option).toHaveCount(0);
  await search.press('Escape');
}

module.exports = { selectManagementTab, expectManagementEntry };
