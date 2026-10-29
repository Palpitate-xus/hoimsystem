# 贡献指南

本文说明 HOIM 项目的本地开发、代码规范和提交要求。

## 一、开发环境准备

### 1.1 Fork 与克隆

```bash
# Fork 本仓库到您的 GitHub 账号，然后克隆

git clone https://github.com/YOUR_USERNAME/hoimsystem.git
cd hoimsystem

# 添加上游仓库
git remote add upstream https://github.com/Palpitate-xus/hoimsystem.git
```

### 1.2 启动后端

```bash
cd fastapi_be
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-build.lock
python -m pip install --require-hashes -r requirements.lock

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

### 1.3 启动前端

```bash
cd vue3-new-ui
npm ci --legacy-peer-deps
npm run serve:rspack
```

访问 http://localhost:8091 即可进入系统。

---

## 二、代码规范

### 2.1 后端（Python）

使用 **ruff** 进行代码检查和格式化：

```bash
cd fastapi_be
ruff check app/
ruff format app/
```

核心规范：
- 遵循 PEP 8
- 函数和变量使用 `snake_case`
- 类名使用 `PascalCase`
- 常量使用 `UPPER_CASE`
- 所有公共函数必须包含类型注解和 docstring

### 2.2 前端（Vue）

沿用现有文件的缩进和格式，提交前运行：

```bash
cd vue3-new-ui
npm run test:unit
npm run build
npm run check:bundle
```

核心规范：
- 使用 Vue 3 Composition API
- 组件名使用 PascalCase
- 变量和函数使用 camelCase
- 优先使用 `<script setup>` 语法

路由 `meta.icon` 使用 Element Plus 的 PascalCase 名称，并在 `src/utils/icons.js` 中显式导入。动态配置通过 `resolveIcon`（兼容入口 `faToElIcon`）获取组件；模板和 `icon`、`prefix-icon` 属性绑定导入的组件对象。顶部图标操作使用带可访问名称的按钮。添加菜单后运行 `tests/iconResolution.test.cjs` 与 `e2e/icon-navigation.spec.js`，检查展开、收起和横向布局。

### 2.3 页面与提示文案

页面优先展示筛选条件、业务数据和操作。菜单、面包屑及标签已标明模块时，省去重复的介绍横幅。

提示直接说明当前状态、具体原因和下一步，例如“缺少执行时间，请补录”“本次未生成草稿”。影响判断的数据范围、适用条件和不确定性写在对应结果旁，注明实际字段、日期或缺项；同一事项说明一次。模型版本和校验信息放在任务详情中。

---

## 三、提交规范

### 3.1 Commit Message 格式

采用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型（type）**：

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 bug |
| `docs` | 文档更新 |
| `style` | 代码格式调整（不影响功能） |
| `refactor` | 重构 |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `chore` | 构建/工具/依赖更新 |
| `ci` | CI/CD 配置 |

**示例**：

```bash
git commit -m "feat(patient): 添加家庭成员管理功能"
git commit -m "fix(doctor): 修复处方开具时库存校验逻辑"
git commit -m "docs(api): 更新挂号接口文档"
```

### 3.2 分支命名

```
feature/<模块名>-<功能描述>   # 新功能
fix/<模块名>-<问题描述>       # Bug 修复
docs/<描述>                  # 文档更新
refactor/<描述>              # 重构
```

---

## 四、Pull Request 流程

1. **创建分支**：从 `master` 分支创建功能分支
   ```bash
   git checkout -b feature/patient-family-member
   ```

2. **开发与提交**：按规范编写代码和提交信息

3. **同步上游**：提交 PR 前同步上游最新代码
   ```bash
   git fetch upstream
   git rebase upstream/master
   ```

4. **执行本地检查**：按 `doc/testing.md` 的提交前命令完成后端、前端和依赖验证

5. **提交 PR**：
   - 标题简洁描述变更内容
   - 正文说明变更原因和影响范围
   - 关联相关 Issue（如有）

---

## 五、数据库变更

如需修改数据库结构：

1. 修改 `fastapi_be/app/models.py` 中的模型定义
2. 生成迁移脚本：
   ```bash
   cd fastapi_be
   alembic revision --autogenerate -m "add family_member table"
   ```
3. 在 PR 中一并提交迁移文件

---

## 六、安全须知

- **切勿**在代码中提交密码、密钥、Token 等敏感信息
- 使用 `.env` 文件管理本地环境变量
- 发现安全漏洞请通过 GitHub Security Advisories 报告，不要公开提交 Issue

---

## 七、常见问题

### Q: 提交 PR 前如何验证？

先按 `doc/testing.md` 执行本地发布检查，修复问题后再提交：

```bash
git add .
git commit -m "fix(scope): 修复本地检查发现的问题"
git push origin your-branch
```

### Q: 如何添加新的 API 接口？

1. 在 `fastapi_be/app/routers/` 对应模块中添加路由
2. 在 `fastapi_be/app/schemas.py` 中添加请求/响应模型
3. 在 `fastapi_be/app/main.py` 中注册路由
4. 更新 `doc/apiDoc.md` 文档
5. 在 `vue3-new-ui/src/api/` 中添加前端 API 调用

---

如有疑问，欢迎提交 [Issue](https://github.com/your-org/hoimsystem/issues) 或参与 [Discussions](https://github.com/your-org/hoimsystem/discussions) 讨论。
