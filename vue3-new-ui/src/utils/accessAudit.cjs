const scopeLabels = { existing: '既有业务范围', assigned: '本人接诊患者' };
const strategy = value => value === null ? '继承' : Array.isArray(value) ? value.length ? `自定义 ${value.length} 项` : '禁止全部业务' : '未记录';
const scope = value => scopeLabels[value] || value || '未记录';
const status = value => value === true ? '停用' : value === false ? '启用' : '未记录';
function accessAudit(detail) {
  let value = detail;
  if (typeof value === 'string') { try { value = JSON.parse(value); } catch { value = null; } }
  const before = value?.before, after = value?.after;
  const complete = before && after && typeof before === 'object' && typeof after === 'object';
  const explicit = complete && Array.isArray(before.allowed_permissions) && Array.isArray(after.allowed_permissions);
  const previous = new Set(explicit ? before.allowed_permissions : []), next = new Set(explicit ? after.allowed_permissions : []);
  return {
    summary: complete ? `${strategy(before.allowed_permissions)} → ${strategy(after.allowed_permissions)}；${scope(before.data_scope)} → ${scope(after.data_scope)}；${status(before.disabled)} → ${status(after.disabled)}` : '权限配置变更',
    before: complete ? before : null, after: complete ? after : null, explicit,
    added: explicit ? after.allowed_permissions.filter(code => !previous.has(code)) : [],
    removed: explicit ? before.allowed_permissions.filter(code => !next.has(code)) : [],
    raw: typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2),
  };
}
module.exports = { accessAudit, strategy, scope, status };
