const roles = [
  ['super_admin', '超级管理员'], ['admin', '管理员'], ['director', '科室主任'],
  ['doctor', '医生'], ['nurse', '护士'], ['pharmacist', '药师'], ['cashier', '收费员'],
  ['guide', '导诊员'], ['lab_technician', '检验技师'], ['registrar', '挂号员'], ['patient', '患者'],
];

export function roleLabel(permissions) {
  return roles.find(([key]) => Array.isArray(permissions) && permissions.includes(key))?.[1] || '用户';
}

export function userInitial(username) {
  return [...(typeof username === 'string' && username.trim() || '用户')][0].toUpperCase();
}
