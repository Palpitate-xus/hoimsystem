# 安全政策

## 支持的版本

| 版本 | 支持状态 |
|------|----------|
| v1.0.x | ✅ 积极维护 |
| < v1.0.0 | ❌ 不再维护 |

## 报告漏洞

如果您发现了安全漏洞，请不要公开提交 Issue。请通过以下方式报告：

- GitHub Security Advisories: [New Advisory](https://github.com/Palpitate-xus/hoimsystem/security/advisories/new)
- 邮件: security@hoimsystem.local

我们会在 48 小时内确认收到报告，并在 7 个工作日内提供修复计划。

## 已知安全注意事项

### 1. MockJS 原型污染（GHSA-mh8j-9jvh-gjf6）

**状态**: 上游无可用修复版本
**影响**: 低（仅在演示/开发环境使用）
**详情**:
- MockJS 库存在原型污染漏洞
- 本项目仅在生产构建时启用 Mock 拦截（`main.js` 中 `process.env.NODE_ENV === 'production'` 条件）
- Mock 数据由项目自身定义，不可被外部用户操控
- 替代方案: 使用 MSW (Mock Service Worker) 替代 MockJS（规划中）

**缓解措施**:
- 生产部署时确保使用真实后端 API（FastAPI），不依赖 Mock 数据
- 定期关注 MockJS 上游修复进展

### 2. 依赖安全扫描

本项目使用以下工具持续监控依赖安全：

- **npm audit**: 前端依赖扫描（每次 CI 构建时运行）
- **pip-audit**: Python 依赖扫描
- **GitHub Dependabot**: 自动安全更新

### 3. 安全配置检查清单

部署前请确保：

- [ ] `SECRET_KEY` 已设置为随机生成的强密钥（`>=32 字符`）
- [ ] `.env` 文件已配置且未提交到版本控制
- [ ] 数据库密码不是默认值
- [ ] 生产环境使用 HTTPS
- [ ] CORS `allow_origins` 已限制为实际域名（不是 `*`）
- [ ] 文件上传目录有适当的权限控制

## 安全更新历史

| 日期 | 漏洞 | 修复版本 | 说明 |
|------|------|----------|------|
| 2026-05-10 | CVE-2026-34073, CVE-2026-39892 (cryptography) | v1.0.0+ | 升级至 >=46.0.7 |
| 2026-05-10 | CVE-2026-32597 (PyJWT) | v1.0.0+ | 升级至 >=2.12.0 |
| 2026-05-10 | CVE-2026-25645 (requests) | v1.0.0+ | 升级至 >=2.33.0 |
| 2026-05-10 | CVE-2026-28684 (python-dotenv) | v1.0.0+ | 升级至 >=1.2.2 |
| 2026-05-10 | CVE-2026-4539 (pygments) | v1.0.0+ | 升级至 >=2.20.0 |
| 2026-05-10 | npm 间接依赖 (minimatch, picomatch, serialize-javascript, immutable) | v1.0.0+ | npm overrides 强制升级 |
