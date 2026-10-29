const messages = {
  PROVIDER_TIMEOUT: '模型服务响应超时，请稍后查看任务记录或联系管理员。',
  PROVIDER_UNAVAILABLE: '暂时无法连接模型服务，请联系管理员检查服务状态。',
  INVALID_PROVIDER_RESPONSE: '模型返回内容无法解析，本次未生成可用结果。',
  INCOMPLETE_RESPONSE: '模型输出不完整，本次未生成可用结果。',
  MODEL_REFUSAL: '模型未提供可用结果，请调整问题后再提交。',
  RESULT_STORAGE_ERROR: '任务结果保存失败，请联系管理员并提供任务编号。',
  WORKER_INTERRUPTED: '任务执行中断，请先核对任务记录，再决定是否重新提交。',
};
const text = value => typeof value === 'string' ? value.trim() : '';
function bodyOf(value) {
  try {
    if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) { if(value.byteLength>65536)return null; value = new TextDecoder().decode(value); }
    return typeof value === 'string' ? JSON.parse(value) : value;
  } catch { return null; }
}
function aiError(error, fallback = '本次请求未完成，请稍后重试。') {
  const body = bodyOf(error?.response?.data), detail = body?.detail;
  const status = Number(error?.response?.status) || 0;
  const raw = text(error?.error_message) || text(detail?.message) || text(detail) || text(body?.msg) || (!error?.response && !error?.isAxiosError ? text(error?.message) : '');
  const candidate = error?.error_code || detail?.code || body?.error_code;
  const code = typeof candidate === 'string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(candidate) ? candidate : '';
  const http = raw.match(/HTTP\s*(\d{3})/i)?.[1] || (status ? String(status) : '');
  const attempts = raw.match(/(?:尝试|attempts?)\s*(\d+\s*\/\s*\d+)/i)?.[1];
  const safe = /[\u3400-\u9fff]/.test(raw) && !/https?:\/\/|sk-[\w-]+|Bearer\s|api[_-]?key|traceback|<\/?\w/i.test(raw);
  let message = safe ? raw.slice(0, 500) : messages[code] || fallback;
  if (!safe && code === 'PROVIDER_HTTP_ERROR') message = ['401', '403'].includes(http) ? '模型服务拒绝访问，请管理员检查模型密钥与授权。' : http === '404' ? '模型服务地址或模型名称不可用，请管理员检查配置。' : http === '429' ? '模型服务繁忙或额度受限，请稍后再提交。' : http ? '模型服务暂时不可用，请稍后查看任务记录或联系管理员。' : safe ? raw.slice(0,500) : fallback;
  if (status === 401) message = '登录已失效，请重新登录。';
  else if (status === 403) message = '当前账号没有此项操作权限，请联系管理员调整授权。';
  else if (status === 409 && !safe) message = '资料、配置或任务状态已变化，请重新核对。';
  else if (status === 429 && !safe) message = '请求过于频繁，请稍后再查询。';
  else if (!status && ['ETIMEDOUT', 'ECONNABORTED'].includes(error?.code)) message = '请求超时，请先核对任务记录。';
  return { message, code, status, details: [code, http && `HTTP ${http}`, attempts && `尝试 ${attempts}`].filter(Boolean).join(' · '), uncertain: (!status || status >= 500) && error?.code !== 'ERR_BLOCKED_ORIGIN' };
}
function aiRequestKey(token, payload) { return JSON.stringify([token,payload], (_, value) => value && typeof value === 'object' && !Array.isArray(value) ? Object.fromEntries(Object.entries(value).sort(([a],[b])=>a<b?-1:a>b?1:0)) : value); }
module.exports = { aiError, aiRequestKey };
