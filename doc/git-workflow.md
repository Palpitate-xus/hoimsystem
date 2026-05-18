# Git 工作流

> 本文档定义项目的分支策略、Commit 规范、Code Review 流程等 Git 协作约定。

---

## 一、分支策略

项目采用简化版 **Git Flow**，三条主分支 + 临时特性分支：

```
┌─────────────────────────────────────────────────────────────┐
│ master      ────●────────●────────●────────●───  生产环境     │
│                 │         │        │        │                │
│ develop     ────┼──●──●──●─●──●──●─┼─●──●──●─    开发主干     │
│                 │  │  │  │ │  │  │ │ │  │  │                 │
│ feature/x   ────┼──●──┘  │ │  │  │ │ │  │  │    特性分支     │
│ feature/y   ────┼─────●──┘ │  │  │ │ │  │  │                 │
│ fix/z       ────┼───────●──┘  │  │ │ │  │  │    修复分支     │
│ hotfix/...  ────●─────────────●──┼─●─┼──┼──┼─   紧急修复     │
└─────────────────────────────────────────────────────────────┘
```

### 1.1 主分支

| 分支 | 用途 | 谁能 push | 保护规则 |
|:----:|:----|:---------|:--------|
| `master` | 生产分支，对应正式发布 | **任何人都不能直接 push**，只接受 PR | 必须 PR + Review + CI 通过 |
| `develop` | 开发主干，合并所有特性 | 维护者可直接 push 小改动 | PR 推荐，但允许直接 push 文档级修改 |

### 1.2 临时分支

| 分支模式 | 用途 | 来源 | 合并到 | 删除时机 |
|:--------|:----|:----|:------|:--------|
| `feature/<name>` | 新功能 | `develop` | `develop` | 合并后 |
| `fix/<name>` | bug 修复 | `develop` | `develop` | 合并后 |
| `hotfix/<name>` | 紧急生产修复 | `master` | `master` + `develop` | 合并后 |
| `docs/<name>` | 仅文档变更 | `develop` | `develop` | 合并后 |
| `refactor/<name>` | 重构 | `develop` | `develop` | 合并后 |
| `chore/<name>` | 构建/工具 | `develop` | `develop` | 合并后 |

### 1.3 分支命名

- 使用小写连字符：`feature/patient-export`、`fix/login-error`
- 短而清晰，描述功能或问题
- 关联 Issue 时可加编号：`feature/123-add-mdt`

---

## 二、Commit 规范

### 2.1 格式

遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**示例：**

```
feat(patient): 新增双向转诊功能

实现患者在不同科室之间的转诊申请流程，
包含转出科室登记、目标科室接收、转诊状态跟踪。

涉及 5 个新 API 和 1 个前端页面。

Closes #42
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### 2.2 type 取值

| Type | 说明 | 示例 |
|:----:|:----|:----|
| `feat` | 新功能 | `feat: 新增手术麻醉模块` |
| `fix` | 修复 bug | `fix: 修复登录后空白页问题` |
| `docs` | 仅文档变更 | `docs: 完善 API 文档` |
| `style` | 格式调整（不影响逻辑） | `style: 调整表格样式` |
| `refactor` | 重构（既非新功能也非修复） | `refactor: 抽取通用工具函数` |
| `perf` | 性能优化 | `perf: 优化患者列表查询` |
| `test` | 测试相关 | `test: 新增登录接口测试` |
| `chore` | 构建/工具/依赖 | `chore: 升级 element-plus 到 2.4` |
| `ci` | CI/CD 配置 | `ci: 添加测试覆盖率上传` |
| `revert` | 回滚 commit | `revert: revert "feat: xxx"` |

### 2.3 scope 取值（可选）

按模块或子系统命名：
- `patient`、`doctor`、`pharmacy`、`charge`、`inpatient`、`exam`、`lab`
- `auth`、`api`、`ui`、`db`、`docker`、`ci`

不强制要求 scope，但有助于快速识别变更范围。

### 2.4 subject 要求

- **中文/英文皆可**，团队内一致即可
- 不超过 50 字符
- 使用动词开头：新增/修复/优化/移除/重命名
- 结尾不加句号
- ❌ 反例：`修改了一些东西` / `update`
- ✅ 正例：`新增手术麻醉模块的麻醉记录功能`

### 2.5 body（可选）

- 描述 **为什么** 改，不是 **改了什么**（diff 已经能看出改了什么）
- 列出关键改动点
- 涉及多个模块时说明依赖关系
- 与 subject 之间空一行

### 2.6 footer（可选）

- 关闭 Issue：`Closes #42` / `Fixes #42`
- 关联 PR：`See #45`
- 协作者：`Co-Authored-By: Name <email>`
- 破坏性变更：`BREAKING CHANGE: 修改了 xxx 接口的返回结构`

---

## 三、典型工作流

### 3.1 开发新功能

```bash
# 1. 同步主干
git checkout develop
git pull origin develop

# 2. 创建特性分支
git checkout -b feature/your-feature

# 3. 开发并提交
# ...编辑代码...
git add .
git commit -m "feat(scope): 描述"

# 4. 推送到远程
git push -u origin feature/your-feature

# 5. 在 GitHub 创建 PR：feature/your-feature -> develop
# 6. CI 通过 + 至少 1 个 Review 通过后，合并
# 7. 合并后删除本地和远程分支
git checkout develop
git pull
git branch -d feature/your-feature
git push origin --delete feature/your-feature
```

### 3.2 修复 bug

```bash
git checkout develop
git pull
git checkout -b fix/login-error

# ...修复...
git add .
git commit -m "fix(auth): 修复 token 过期后未跳转登录页"
git push -u origin fix/login-error
# 创建 PR -> develop
```

### 3.3 紧急生产修复（hotfix）

```bash
# 1. 从 master 拉取（不是 develop！）
git checkout master
git pull
git checkout -b hotfix/critical-bug

# 2. 修复并提交
# ...
git commit -m "fix(critical): 修复支付接口空指针"

# 3. 同时合并到 master 和 develop
git push -u origin hotfix/critical-bug
# 创建 2 个 PR：
# - hotfix/critical-bug -> master
# - hotfix/critical-bug -> develop
```

### 3.4 同步主干变更到特性分支

如果你的特性分支落后于 develop，需要同步：

```bash
git checkout feature/your-feature

# 方式一：merge（保留分支历史）
git fetch origin
git merge origin/develop

# 方式二：rebase（线性历史，推荐）
git fetch origin
git rebase origin/develop

# 解决冲突后继续
git add .
git rebase --continue

# 强制推送（个人分支可以）
git push --force-with-lease
```

---

## 四、Code Review 流程

### 4.1 提交 PR 前自查

- [ ] 已运行测试通过（`pytest`）
- [ ] 前端构建无报错（`npm run build`）
- [ ] 代码符合 [coding-standards.md](coding-standards.md)
- [ ] Commit message 符合 Conventional Commits
- [ ] 已删除调试代码（`console.log`、`print`）
- [ ] 已更新相关文档
- [ ] 已填写 [PR 模板](../.github/PULL_REQUEST_TEMPLATE.md)

### 4.2 评审人职责

- 24 小时内响应（工作日）
- 重点看：
  - **正确性** — 是否解决了问题？有没有引入新 bug？
  - **可读性** — 命名清晰？逻辑直观？
  - **可维护性** — 是否过度抽象？是否方便后续修改？
  - **安全性** — 有没有 SQL 注入、XSS、权限漏洞？
  - **性能** — N+1 查询？大循环？大对象？
  - **测试** — 是否有测试覆盖关键路径？

### 4.3 评审标记

- ✅ **Approve** — 同意合并
- 💬 **Comment** — 提建议但不阻塞合并
- ❌ **Request Changes** — 必须修改才能合并

### 4.4 合并方式

| 方式 | 适用场景 | 说明 |
|:----:|:--------|:----|
| **Squash and Merge** | 推荐默认 | 多个 commit 压缩成一个，主干历史更整洁 |
| **Rebase and Merge** | 分支已是干净的单条线 | 保留原始 commit，无 merge commit |
| **Create Merge Commit** | 长期分支合并 | 保留分支结构，但主干会有 merge commit |

> 默认使用 **Squash and Merge**，特殊情况由评审人决定。

---

## 五、特殊场景

### 5.1 误提交敏感信息怎么办？

**最佳做法**：**立即** 旋转密钥/密码，因为提交历史已经泄露。

如果还没 push：
```bash
# 撤销最近一次 commit（保留改动）
git reset --soft HEAD~1
# 修改后重新提交
```

如果已经 push：
- 不要直接 `git push --force`，会破坏其他人的工作树
- 联系维护者处理
- 旋转所有相关密钥

### 5.2 想撤销已合并的 PR

```bash
git revert <commit-hash>
git push
```

不要用 `git reset --hard` 强推主分支。

### 5.3 多人协作同一分支

避免长时间持有分支，频繁同步：
```bash
git fetch
git rebase origin/feature/shared  # 同步队友的提交
```

### 5.4 commit 太多想合并

在 PR 合并时用 "Squash and Merge" 自动处理。

如果想本地合并：
```bash
git rebase -i HEAD~5  # 合并最近 5 个 commit
# 把 pick 改为 squash 即可
```

---

## 六、Git 配置建议

### 6.1 全局配置

```bash
# 设置用户信息
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# 默认 pull 用 rebase（避免不必要的 merge commit）
git config --global pull.rebase true

# 默认推送当前分支
git config --global push.default current

# 颜色输出
git config --global color.ui auto

# 别名（可选）
git config --global alias.st status
git config --global alias.co checkout
git config --global alias.br branch
git config --global alias.lg "log --oneline --graph --all"
```

### 6.2 .gitignore

项目已配置 `.gitignore`，常见忽略：
- `node_modules/`、`venv/`、`__pycache__/`
- `*.pyc`、`.env`、`*.db`、`.DS_Store`
- `dist/`、`build/`
- `.vscode/settings.json`（IDE 配置个人化）

如果有新的应忽略文件类型，提交 PR 更新 `.gitignore`。

---

## 七、不要做的事

❌ **绝对禁止**：
- 直接 push 到 master
- 用 `--no-verify` 跳过 pre-commit hook（除非紧急且明确告知评审人）
- 修改已合并的公共历史（`git push --force` 到 master/develop）
- 提交敏感信息（密码、密钥、个人数据）

⚠️ **强烈不推荐**：
- 单个 commit 包含多种类型的变更（如同时 feat + fix + refactor）
- 单个 PR 超过 1000 行变更（除文档外）
- 长时间持有特性分支（>1 周）
- commit message 写 "fix"、"update"、"修改" 这种无意义内容

---

## 八、参考资料

- [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)
- [Git Flow 工作流](https://nvie.com/posts/a-successful-git-branching-model/)
- [GitHub Flow（简化版）](https://docs.github.com/cn/get-started/quickstart/github-flow)
- [How to write a git commit message](https://chris.beams.io/posts/git-commit/)
