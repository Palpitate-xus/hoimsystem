import request from '@/utils/request';
const policyPath = (kind, key) => `access/policies/${encodeURIComponent(kind)}/${encodeURIComponent(key)}`;
export const getAccessCatalog = () => request({ url: 'access/catalog', method: 'get' });
export const getAccessPolicy = (kind, key) => request({ url: policyPath(kind, key), method: 'get' });
export const saveAccessPolicy = (kind, key, data) => request({ url: policyPath(kind, key), method: 'put', data });
export const getAccessAudit = params => request({ url: 'access/audit', method: 'get', params });
export const getMyAccess = () => request({ url: 'access/me', method: 'get' });
