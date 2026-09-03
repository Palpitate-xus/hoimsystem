# 安全政策

## 支持的版本

| 版本 | 支持状态 |
|------|----------|
| 当前 `master` / 未发布版 | ✅ 积极维护 |
| v2.0.x | ✅ 接收高危与严重漏洞修复 |
| < v2.0.0 | ❌ 不再维护 |

## 报告漏洞

如果您发现了安全漏洞，请不要公开提交 Issue。请通过以下方式报告：

- GitHub Security Advisories: [New Advisory](https://github.com/Palpitate-xus/hoimsystem/security/advisories/new)

我们会在 48 小时内确认收到报告，并在 7 个工作日内提供修复计划。

## 已知安全注意事项

### 1. 依赖安全扫描

本项目使用以下工具检查依赖安全：

- **npm audit**：前端生产与开发依赖，发布前在本地以 low 级别检查
- **pip-audit**：后端 `requirements.txt`，发布前在本地检查已知漏洞
- **GitHub Dependabot**：每周检查 npm、pip 和 Docker 依赖；它不执行 GitHub Actions

2026-09-03 已彻底移除无修复版本的 `mockjs` 运行时，用本地确定性数据生成器保留开发 mock 功能；同时更新 `qs` 及 `browserslist`、`nanoid`、`postcss-selector-parser` 等传递依赖。当前 lockfile 的 `npm audit` 为 0 告警。GitHub 默认分支上的旧 Dependabot 告警会在修复提交推送并由 GitHub 重新扫描后关闭。

### 2. 安全配置检查清单

部署前请确保：

- [ ] `SECRET_KEY` 已设置为随机生成的强密钥（`>=32 字符`）
- [ ] `.env` 文件已配置且未提交到版本控制
- [ ] 数据库密码不是默认值
- [ ] 生产环境使用 HTTPS
- [ ] CORS `allow_origins` 已限制为实际域名（不是 `*`）
- [ ] 文件上传目录有适当的权限控制
- [ ] 生产未运行演示账号脚本；首个管理员通过 `bootstrap_admin.py` 交互创建

## 安全更新历史

| 日期 | 漏洞 | 修复版本 | 说明 |
|------|------|----------|------|
| 2026-05-10 | CVE-2026-34073, CVE-2026-39892 (cryptography) | v1.0.0+ | 升级至 >=46.0.7 |
| 2026-05-10 | CVE-2026-32597 (PyJWT) | v1.0.0+ | 升级至 >=2.12.0 |
| 2026-05-10 | CVE-2026-25645 (requests) | v1.0.0+ | 升级至 >=2.33.0 |
| 2026-05-10 | CVE-2026-28684 (python-dotenv) | v1.0.0+ | 升级至 >=1.2.2 |
| 2026-05-10 | CVE-2026-4539 (pygments) | v1.0.0+ | 升级至 >=2.20.0 |
| 2026-05-10 | npm 间接依赖 (minimatch, picomatch, serialize-javascript, immutable) | v1.0.0+ | npm overrides 强制升级 |
| 2026-09-03 | MockJS 原型污染及 npm 直接/传递依赖告警 | 未发布版 | 移除 MockJS，更新/覆盖到已修复版本，发布前执行 `npm audit` |
