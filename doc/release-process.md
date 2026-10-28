# 发布流程

`master` 保存已验收的发布版本，功能在工作分支上按小功能提交。版本采用 `MAJOR.MINOR.PATCH`，项目根目录 `VERSION`、后端 `/api/version` 和前端 npm 元数据保持一致；发布记录写入 `CHANGELOG.md`。

## 准备与验证

使用 Python 3.12、Node.js 24 和 Docker Compose。先按 [依赖维护](dependencies.md) 安装锁定依赖，再运行：

```bash
python fastapi_be/scripts/audit_dependencies.py --output /tmp/hoim-release-audit-001
cd vue3-new-ui
npm ci --legacy-peer-deps
npm run test:unit
npm run build
npm run check:bundle
cd ..
python scripts/check_release.py
```

后端全量回归、PostgreSQL 事务检查、浏览器业务验收及持续压测按 [测试指南](testing.md) 执行。保存收集清单、失败与整文件复验；结果按测试节点去重，不能将重跑数量累加为通过数。模型质量评估独立于工程回归。

修改界面来源后使用正式生成器更新完整数据，随后重新构建：

```bash
cd vue3-new-ui
node scripts/generate-element-plus-style-entry.cjs
node scripts/generate-public-interface-text-pool.cjs
npm run build
```

## 归档与版本管理

验证通过后，在当前分支提交实现、文档和报告。保持工作区干净，检查 `master` 能快进到已验收提交，再执行：

```bash
git switch master
git merge --ff-only feature/ai-hospital-platform
git tag -a v2.1.0 -m "Release v2.1.0"
```

远端发布由维护者执行；本地提交和标签不会自动上传：

```bash
git push origin master
git push origin v2.1.0
```

## 部署与回滚

本地演示使用 `python scripts/local_preview.py start`，监听 `0.0.0.0:51891`，API 监听 `51800`。部署前备份独立数据库、Redis 数据和私有环境文件，保持数据库主版本与数据卷一致。

生产部署先构建并记录镜像 ID，再运行迁移、API、worker、调度器和前端。以就绪探针、版本接口、角色登录和关键业务写入核对实际运行版本。镜像安全审计结果与业务验收分开归档。

回滚优先恢复上一版已验证的应用镜像和配置。数据库不执行盲目降级；涉及不可逆数据变化时，恢复备份到独立数据库并核对后切换，保留原数据供排查。
