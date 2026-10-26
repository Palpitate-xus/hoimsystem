const { expect } = require('@playwright/test');

// Exercise disclosure through the visible control while retaining the original
// text/identity assertions made by each business-flow test.
async function openNativeDetails(scope, label, options = {}) {
  const target = scope.getByLabel(label, { exact: true });
  await expect(target).toBeAttached({ timeout: options.timeout ?? 15000 });
  const details = target.locator('xpath=ancestor::details[1]');
  if (await details.getAttribute('open') === null) {
    await details.locator(':scope > summary').click();
  }
  await expect(target).toBeVisible({ timeout: options.timeout ?? 15000 });
}

module.exports = { openNativeDetails };

async function fillNativeDetails(scope, label, value) {
  await openNativeDetails(scope, label);
  await scope.getByLabel(label, { exact: true }).fill(value);
}
module.exports.fillNativeDetails = fillNativeDetails;

async function openNativeTextDetails(scope, text, options = {}) {
  const target = scope.getByText(text, { exact: true });
  await expect(target).toBeAttached({ timeout: options.timeout ?? 15000 });
  const details = target.locator('xpath=ancestor::details[1]');
  if (await details.getAttribute('open') === null) {
    await details.locator(':scope > summary').click();
  }
  await expect(target).toBeVisible({ timeout: options.timeout ?? 15000 });
}
module.exports.openNativeTextDetails = openNativeTextDetails;
