# 贡献指南

感谢您对医院门诊信息管理系统（HIS-OP）的关注！本文档将帮助您快速参与项目贡献。

## 一、开发环境准备

### 1.1 Fork 与克隆

```bash
# Fork 本仓库到您的 GitHub 账号，然后克隆

git clone https://github.com/YOUR_USERNAME/hoimsystem.git
cd hoimsystem

# 添加上游仓库
git remote add upstream https://github.com/original-owner/hoimsystem.git
```

### 1.2 启动后端

```bash
cd fastapi_be
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

### 1.3 启动前端

```bash
cd vue3-new-ui
npm install --legacy-peer-deps
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

使用 **Prettier** 进行格式化：

```bash
cd vue3-new-ui
npx prettier --write "src/**/*.{js,vue}"
```

核心规范：
- 使用 Vue 3 Composition API
- 组件名使用 PascalCase
- 变量和函数使用 camelCase
- 优先使用 `<script setup>` 语法

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

4. **确保 CI 通过**：推送后确认 GitHub Actions 全部通过

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

### Q: 提交 PR 后 CI 失败怎么办？

查看 GitHub Actions 日志，修复对应问题后重新推送：

```bash
git add .
git commit --amend --no-edit
git push -f origin your-branch
```

### Q: 如何添加新的 API 接口？

1. 在 `fastapi_be/app/routers/` 对应模块中添加路由
2. 在 `fastapi_be/app/schemas.py` 中添加请求/响应模型
3. 在 `fastapi_be/app/main.py` 中注册路由
4. 更新 `doc/apiDoc.md` 文档
5. 在 `vue3-new-ui/src/api/` 中添加前端 API 调用

---

如有疑问，欢迎提交 [Issue](https://github.com/your-org/hoimsystem/issues) 或参与 [Discussions](https://github.com/your-org/hoimsystem/discussions) 讨论。
