const test = require('node:test');
const assert = require('node:assert/strict');
const { accessAudit } = require('../src/utils/accessAudit.cjs');
const policy = (allowed_permissions, data_scope = 'existing', disabled = false) => ({ allowed_permissions, data_scope, disabled });
const codes = (start, count) => Array.from({ length: count }, (_, i) => `GET /api/clinical/record${start + i}`);

test('large audit summaries stay bounded while complete original values and actual permission changes survive', () => {
  const detail = { before: policy(codes(0, 519)), after: policy(codes(100, 519), 'assigned', true), version: 9 };
  const raw = JSON.stringify(detail);
  const result = accessAudit(raw);
  assert.equal(result.summary, '自定义 519 项 → 自定义 519 项；既有业务范围 → 本人接诊患者；启用 → 停用');
  assert.ok(result.summary.length < 100);
  assert.equal(result.summary.includes('/api/'), false);
  assert.deepEqual(result.added, codes(519, 100));
  assert.deepEqual(result.removed, codes(0, 100));
  assert.equal(result.raw, raw);
  assert.deepEqual(JSON.parse(result.raw), detail);
  assert.equal(result.before.allowed_permissions.length, 519);
  assert.equal(result.after.allowed_permissions.length, 519);
});

test('summarizing a frozen audit object does not mutate its policies or permission order', () => {
  const before = Object.freeze(policy(Object.freeze(['GET /api/b', 'GET /api/a'])));
  const after = Object.freeze(policy(Object.freeze(['GET /api/a', 'POST /api/c'])));
  const detail = Object.freeze({ before, after });
  const result = accessAudit(detail);
  assert.deepEqual(result.added, ['POST /api/c']);
  assert.deepEqual(result.removed, ['GET /api/b']);
  assert.deepEqual(JSON.parse(result.raw), detail);
  assert.strictEqual(result.before, before);
  assert.strictEqual(result.after, after);
});

for (const [before, after, summary] of [
  [null, [], '继承 → 禁止全部业务'],
  [[], null, '禁止全部业务 → 继承'],
  [null, ['GET /api/a'], '继承 → 自定义 1 项'],
  [['GET /api/a'], null, '自定义 1 项 → 继承'],
]) test(`${summary} preserves inherited versus explicit policies without inventing historical effective grants`, () => {
  const detail = { before: policy(before), after: policy(after) };
  const result = accessAudit(detail);
  assert.ok(result.summary.startsWith(summary));
  assert.equal(result.explicit, false);
  assert.deepEqual(result.added, []);
  assert.deepEqual(result.removed, []);
  assert.deepEqual(JSON.parse(result.raw), detail);
});

test('empty explicit policies still show scope and activation changes and have no permission deltas', () => {
  const result = accessAudit({ before: policy([], 'assigned', true), after: policy([], 'existing', false) });
  assert.equal(result.summary, '禁止全部业务 → 禁止全部业务；本人接诊患者 → 既有业务范围；停用 → 启用');
  assert.equal(result.explicit, true);
  assert.deepEqual(result.added, []);
  assert.deepEqual(result.removed, []);
});

test('legacy records retain their full raw detail even when no structured comparison exists', () => {
  for (const raw of ['{"version":2,"note":"历史审计"}', 'unstructured historical audit']) {
    const result = accessAudit(raw);
    assert.equal(result.summary, '权限配置变更');
    assert.equal(result.before, null);
    assert.equal(result.after, null);
    assert.equal(result.raw, raw);
    assert.deepEqual(result.added, []);
    assert.deepEqual(result.removed, []);
  }
});
