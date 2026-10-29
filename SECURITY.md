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

- **npm audit**：前端锁文件的生产与开发依赖，任何严重级别的漏洞都会使检查失败
- **pip-audit**：检查 18 份 Python 哈希锁文件，覆盖 API、构建、测试及独立模型环境
- **GitHub Actions**：PR、`master` 推送、每周定时及手动执行锁文件校验与完整依赖审计，保留报告 14 天
- **GitHub Dependabot**：每周检查 npm、pip、Docker 和 GitHub Actions 更新

审计逐项核对包名和精确版本，报告缺失、损坏、漏包、跳过项、重复项或扫描工具失败都会使检查失败。Torch CPU 轮子保留安装版本，审计时使用对应的公开发行版本查询通告。

本地复现：

```bash
python fastapi_be/scripts/lock_dependencies.py
python fastapi_be/scripts/audit_dependencies.py --output dependency-audit
```

输出目录须为新目录。发现 GitHub 告警时，记录包名、依赖文件路径、GHSA/CVE 与受影响版本，再对照默认分支及当前锁文件定位。2026-10-29 的本地与远端依赖对照、PyPI/OSV/npm 结果见[审计记录](doc/validation/2026-10-29-dependabot.md)。

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
