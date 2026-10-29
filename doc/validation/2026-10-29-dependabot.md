# 依赖与 Dependabot 对照 · 2026-10-29

收到的 GitHub 推送输出报告默认分支存在 12 条漏洞：9 条 high、3 条 moderate。本机没有读取仓库安全告警的认证，尚待取得包名、依赖文件路径和 GHSA/CVE 明细逐条定位。

## 对照结果

Git 远端默认分支为 `master`，检查时指向 `5d7bc95a99c177545f302abeb78eef0373546aec`。与本轮开始的本地 `619268fbcca3dff54afdb2efdb5f4f2e34c3075c` 比较，19 份 Python requirements 输入、18 份哈希锁、锁清单及前端依赖清单/锁文件均相同。既有依赖安全更新已包含在远端历史中。

| 检查 | 覆盖 | 结果 |
| --- | --- | --- |
| Python 哈希锁与输入 | 18 份锁、9 个独立环境 | 全部一致 |
| PyPI advisory 全新查询 | 99 个唯一包版本 | 0 漏洞、0 跳过 |
| OSV 交叉查询 | 同 99 个包版本 | 0 漏洞、0 跳过 |
| 远端 Python 版本独立审计 | 同 99 个包版本 | 0 漏洞、0 跳过 |
| 当前 npm audit | 生产与开发依赖 | 0 漏洞 |
| 远端锁文件隔离 npm audit | 与当前逐字节相同的锁文件 | 0 漏洞 |
| 完整脚本审计 | 18 份 Python 锁文件及 npm | 通过，报告完整 |
| 审计完整性回归 | 40 项 | 全部通过 |
| workflow YAML 与 actionlint | 新增工作流 | 通过 |

本轮保留依赖版本，新增审计完整性检查及自动执行配置。机器结果与源文件 SHA-256 见[JSON 记录](2026-10-29-dependabot.json)。

## 已提交的改进

- GitHub Actions 在 PR、master 推送、每周及手动触发时检查全部锁文件与 npm，并保留报告 14 天。
- workflow 使用只读仓库权限、关闭 checkout 凭据持久化、固定官方 Action SHA；扫描不安装应用或模型依赖。
- Python 报告必须覆盖每个请求的包名和精确版本；缺失、坏 JSON、漏包、跳过、重复、错误版本及扫描工具失败都使检查失败。
- npm 报告同时核对漏洞明细与总数，空输出或不完整报告不能作为零漏洞结果。
- 锁清单必须覆盖每份 requirements 环境；新增或移除环境后须同步完整锁文件清单。

40 项测试覆盖上述失败路径及命令退出码、持久化 summary，包含扫描工具错误地返回 0 时仍拒绝不完整或有漏洞报告的情形。

本轮未推送，GitHub 上的新工作流尚未执行。GitHub 12 条告警的包与通告明细仍待提供；本记录中的 0 是上述本地审计结果。

## 复现与证据

```bash
python fastapi_be/scripts/audit_dependencies.py --output dependency-audit
python -m pytest fastapi_be/tests/test_dependency_audit.py
```

使用新输出目录。原始证据保存在本机 `.local-preview/dependabot-python-before/`、`.local-preview/dependabot-origin-frontend/`、`.local-preview/dependabot-all-env-final/` 及 `.local-preview/dependabot-audit-gate-final.xml`。本轮修改涉及审计与 CI，不改变应用依赖、模型身份或本地预览运行环境。
