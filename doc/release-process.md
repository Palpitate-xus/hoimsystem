# 发布流程

> 本文档定义项目的版本发布流程，包括版本号规则、发布步骤、回滚方案。

---

## 一、版本号规则

遵循 [语义化版本 SemVer 2.0](https://semver.org/lang/zh-CN/)：

```
主版本号(MAJOR).次版本号(MINOR).修订号(PATCH)

例：v1.2.3
    │ │ │
    │ │ └── 修订号：bug 修复，向下兼容
    │ └──── 次版本号：新功能，向下兼容
    └────── 主版本号：破坏性变更（API 改动、数据结构变更）
```

### 1.1 何时升 MAJOR（主版本号）

- 移除/重命名/修改 API 入参或响应结构
- 数据库表结构破坏性变更（删字段、改类型）
- 鉴权机制变更
- 配置文件结构变更

### 1.2 何时升 MINOR（次版本号）

- 新增 API 接口
- 新增数据库表/字段（向下兼容）
- 新增前端页面或功能
- 重要的非破坏性优化

### 1.3 何时升 PATCH（修订号）

- bug 修复
- 文档变更
- 性能优化（不影响行为）
- 内部重构（外部行为不变）

### 1.4 预发布版本

- `v1.2.0-alpha.1` — 内部测试
- `v1.2.0-beta.1` — 公开测试
- `v1.2.0-rc.1` — 发布候选

---

## 二、发布前准备

### 2.1 功能冻结

发布前 1-3 天进入冻结期：
- 不再合并新功能（feat）到 develop
- 只允许 bug 修复（fix）和文档变更（docs）
- 已合并的功能进入测试阶段

### 2.2 测试清单

- [ ] 所有自动化测试通过（`pytest`）
- [ ] 前端构建无报错（`npm run build`）
- [ ] 关键业务流程手工回归测试：
  - [ ] 登录/登出
  - [ ] 患者预约挂号
  - [ ] 医生开处方
  - [ ] 药师审方发药
  - [ ] 收费员收费
  - [ ] 患者报到签到
  - [ ] 医嘱执行
  - [ ] 出院结算
- [ ] 性能测试（如有大改）
- [ ] 浏览器兼容性测试（Chrome / Firefox / Edge）

### 2.3 文档更新

- [ ] 更新 `CHANGELOG.md` 添加新版本条目
- [ ] 更新 `README.md` 中的版本号、统计数据
- [ ] 更新 API 文档（如有 API 变更）
- [ ] 更新数据库文档（如有 schema 变更）
- [ ] 更新 [todos.md](todos.md) 标记已完成项

### 2.4 数据库迁移检查

- [ ] 所有 schema 变更都有 Alembic migration script
- [ ] 迁移脚本在测试环境验证过
- [ ] 迁移过程考虑了数据兼容性（如默认值）
- [ ] 大表迁移有锁表风险评估

---

## 三、发布流程

### 3.1 develop → master 合并

```bash
# 1. 从最新的 develop 创建发布分支
git checkout develop
git pull
git checkout -b release/v1.2.0

# 2. 在发布分支上做最后调整：
#    - 更新版本号（package.json, requirements.txt, etc.）
#    - 更新 CHANGELOG.md
#    - 最后的 bug 修复
git commit -m "chore(release): bump version to v1.2.0"
git push -u origin release/v1.2.0

# 3. 创建 PR：release/v1.2.0 -> master
#    至少 1 个 review 通过

# 4. 合并后打 tag
git checkout master
git pull
git tag -a v1.2.0 -m "Release v1.2.0"
git push origin v1.2.0

# 5. 合并回 develop（确保 develop 包含发布分支的修改）
git checkout develop
git merge master
git push
```

### 3.2 创建 GitHub Release

1. 进入 GitHub 仓库 → Releases → Draft new release
2. 选择刚才打的 tag `v1.2.0`
3. 填写 Release Notes（从 CHANGELOG.md 复制）
4. 上传构建产物（可选）：
   - 前端：`vue3-new-ui/dist.zip`
   - 后端：（无需）
5. 发布

### 3.3 部署到生产环境

```bash
# 服务器上
cd /opt/hoimsystem

# 1. 备份当前版本
sudo systemctl stop hoimsystem
cp -r fastapi_be fastapi_be.bak.$(date +%Y%m%d)
cp -r vue3-new-ui/dist vue3-new-ui/dist.bak.$(date +%Y%m%d)

# 2. 拉取新代码
git fetch origin
git checkout v1.2.0

# 3. 后端：更新依赖、运行迁移
cd fastapi_be
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

# 4. 前端：构建
cd ../vue3-new-ui
npm install --legacy-peer-deps
npm run build

# 5. 重启服务
sudo systemctl start hoimsystem
sudo nginx -s reload

# 6. 验证
curl http://localhost:8000/         # 后端
curl -I http://your-domain.com/     # 前端
```

### 3.4 发布通告

发布完成后通知：
- 团队群通告
- 邮件通知关键干系人
- 更新文档站点（如有）

包含信息：
- 版本号
- 发布时间
- 主要变更（从 CHANGELOG.md 摘要）
- 破坏性变更（如有）
- 升级注意事项

---

## 四、版本历史

| 版本 | 发布日期 | 主要变更 |
|:----:|:-------:|:--------|
| v1.1.0 | 2026-05-18 | 住院/手术/体检/EMR/MDT/操作日志中间件 |
| v1.0.0 | 2026-05-10 | 门诊全流程首版发布 |

详细变更见 [CHANGELOG.md](../CHANGELOG.md)。

---

## 五、回滚方案

如果生产环境发现严重问题，需要立即回滚。

### 5.1 快速回滚（5 分钟内）

```bash
# 服务器上
cd /opt/hoimsystem
sudo systemctl stop hoimsystem

# 恢复备份
rm -rf fastapi_be vue3-new-ui/dist
mv fastapi_be.bak.20260518 fastapi_be
mv vue3-new-ui/dist.bak.20260518 vue3-new-ui/dist

# 数据库回滚（如果做了迁移）
cd fastapi_be
source venv/bin/activate
alembic downgrade -1  # 回滚一个版本

# 重启
sudo systemctl start hoimsystem
sudo nginx -s reload
```

### 5.2 完整回滚

```bash
# 1. Git 上回滚到上一个 tag
git checkout v1.1.0

# 2. 重新部署
# （重复 3.3 步骤）
```

### 5.3 数据库不可回滚的情况

如果迁移包含：
- 删除列/表
- 修改列类型导致数据丢失
- 大量数据变更

**回滚前必须**：
- 恢复数据库备份
- 重启服务

---

## 六、热修复（Hotfix）

针对生产环境严重 bug 的快速修复，跳过常规发布流程：

```bash
# 1. 从 master 拉取（不是 develop）
git checkout master
git pull
git checkout -b hotfix/critical-bug

# 2. 修复 + 测试
# ...

# 3. 提交 PR -> master
#    跳过部分流程，但仍需 review

# 4. 合并后立即发布
git tag -a v1.2.1 -m "Hotfix: 修复 xxx"
git push origin v1.2.1

# 5. 同步回 develop
git checkout develop
git merge master
git push

# 6. 立即部署到生产
```

---

## 七、发布检查表（模板）

每次发布前打印此表逐项确认：

```markdown
# Release v1.x.x Checklist

## 代码
- [ ] develop 分支已合并所有计划功能
- [ ] 无未关闭的高优先级 Bug Issue
- [ ] 所有 PR 已 review 并合并

## 测试
- [ ] 后端 pytest 全部通过
- [ ] 前端 npm run build 成功
- [ ] 手工回归 8 个核心流程
- [ ] 浏览器兼容性测试

## 文档
- [ ] CHANGELOG.md 已更新
- [ ] README.md 统计数据已更新
- [ ] API 文档同步
- [ ] 数据库文档同步

## 数据库
- [ ] 所有 schema 变更有 migration
- [ ] migration 在测试环境验证
- [ ] 备份生产数据库

## 部署
- [ ] release 分支已合并到 master
- [ ] 已打 git tag
- [ ] GitHub Release 已发布
- [ ] 生产环境已部署
- [ ] 烟雾测试通过（关键接口、关键页面）

## 通告
- [ ] 团队群已通知
- [ ] 关键干系人已邮件通知
```

---

## 八、版本号自动化（可选）

可以使用工具自动管理版本号：

```bash
# 后端（Python）：bump2version
pip install bump2version
bump2version patch  # 1.2.0 -> 1.2.1
bump2version minor  # 1.2.1 -> 1.3.0
bump2version major  # 1.3.0 -> 2.0.0

# 前端（npm）：npm version
cd vue3-new-ui
npm version patch
npm version minor
npm version major
```

需要在 `setup.cfg` 或 `.bumpversion.cfg` 中配置版本号位置。

---

## 九、参考资料

- [语义化版本 SemVer](https://semver.org/lang/zh-CN/)
- [Keep a Changelog](https://keepachangelog.com/zh-CN/)
- [GitHub Releases 文档](https://docs.github.com/cn/repositories/releasing-projects-on-github/about-releases)
