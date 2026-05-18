# 文档总览

> 本目录包含 HIS-OP 医院门诊信息管理系统的全部技术文档。
> 不同角色可按下方导航直达对应文档。

---

## 📚 文档导航

### 🆕 新人快速上手

1. **[项目主 README](../README.md)** — 项目概览、技术栈、快速启动
2. **[开发环境搭建](dev-setup.md)** — 详细的本地环境配置、IDE 配置、调试技巧
3. **[用户操作手册](user-manual.md)** — 各角色的具体操作流程
4. **[常见问题 FAQ](troubleshooting.md)** — 27 个典型问题与解决方案

### 🏗 架构师 / 技术负责人

1. **[架构文档](architecture.md)** — 系统架构、技术选型、设计决策
2. **[ADR 决策记录](adr/README.md)** — 重要架构决策的备忘录
3. **[需求文档](demandDoc.md)** — 业务需求与非功能需求
4. **[性能指南](performance.md)** — 性能优化方法
5. **[路线图](todos.md)** — 已完成功能与未来规划

### 💻 后端开发

1. **[编码规范](coding-standards.md)** — Python/Vue/数据库/Git 全规范
2. **[API 文档](apiDoc.md)** — 247 个接口的入参、响应、错误码
3. **[数据库文档](databaseDoc.md)** — 61 张表的字段、索引、ER 关系
4. **[数据字典](data-dictionary.md)** — 状态码、枚举值统一定义
5. **[架构文档](architecture.md)** — 中间件、依赖、安全机制
6. **[测试指南](testing.md)** — pytest 测试编写与运行

### 🎨 前端开发

1. **[编码规范](coding-standards.md)** — Vue 3 组件规范、样式工具类
2. **[API 文档](apiDoc.md)** — 后端接口规范
3. **[用户操作手册](user-manual.md)** — 各页面的业务流程
4. **[架构文档](architecture.md)** — 前端目录约定与组件复用
5. **[测试指南](testing.md)** — Vitest / Playwright 测试

### 🚀 运维 / DevOps

1. **[部署文档](deployDoc.md)** — Docker、Nginx、Systemd、HTTPS、Alembic
2. **[监控与运维](monitoring.md)** — 日志、告警、健康检查、Runbook
3. **[性能指南](performance.md)** — 数据库慢查询、容量规划
4. **[发布流程](release-process.md)** — 版本号、发布步骤、回滚
5. **[安全策略](../SECURITY.md)** — 安全漏洞上报流程

### 👥 业务方 / 测试

1. **[需求文档](demandDoc.md)** — 业务场景描述
2. **[用户操作手册](user-manual.md)** — 操作步骤与示例
3. **[术语表](glossary.md)** — 医疗 + 技术术语
4. **[数据字典](data-dictionary.md)** — 状态码与枚举值

### 🤝 贡献者 / 协作者

1. **[贡献指南](../CONTRIBUTING.md)** — 如何提交贡献
2. **[Git 工作流](git-workflow.md)** — 分支策略、Commit 规范、Review
3. **[行为准则](../CODE_OF_CONDUCT.md)** — 社区行为准则
4. **[GitHub 模板](../.github/)** — Issue/PR 模板

---

## 📋 文档清单

### 入门与日常开发

| 文件 | 说明 | 主要受众 |
|:----:|:-----|:--------:|
| [dev-setup.md](dev-setup.md) | 开发环境搭建指南 | 新人开发者 |
| [coding-standards.md](coding-standards.md) | 编码规范 | 所有开发者 |
| [testing.md](testing.md) | 测试指南 | 所有开发者 |
| [troubleshooting.md](troubleshooting.md) | 常见问题 FAQ | 所有人 |
| [user-manual.md](user-manual.md) | 用户操作手册 | 业务方、测试 |

### 架构与设计

| 文件 | 说明 | 主要受众 |
|:----:|:-----|:--------:|
| [architecture.md](architecture.md) | 系统架构文档 | 架构师 |
| [adr/](adr/README.md) | 架构决策记录 | 架构师 |
| [demandDoc.md](demandDoc.md) | 需求文档 | 全员 |
| [apiDoc.md](apiDoc.md) | API 接口文档 | 前后端 |
| [databaseDoc.md](databaseDoc.md) | 数据库设计文档 | 后端、DBA |
| [data-dictionary.md](data-dictionary.md) | 业务数据字典 | 全员 |
| [glossary.md](glossary.md) | 术语表 | 全员 |

### 部署与运维

| 文件 | 说明 | 主要受众 |
|:----:|:-----|:--------:|
| [deployDoc.md](deployDoc.md) | 部署文档 | 运维 |
| [monitoring.md](monitoring.md) | 监控与运维 | 运维 |
| [performance.md](performance.md) | 性能优化指南 | 架构师、运维 |
| [release-process.md](release-process.md) | 发布流程 | 维护者 |

### 协作

| 文件 | 说明 | 主要受众 |
|:----:|:-----|:--------:|
| [git-workflow.md](git-workflow.md) | Git 工作流 | 所有开发者 |
| [todos.md](todos.md) | 路线图与待办 | 全员 |

---

## 🔗 项目根目录文档

| 文件 | 位置 | 说明 |
|:----:|:----:|:-----|
| 主 README | [../README.md](../README.md) | 项目入口 |
| 英文 README | [../README.en.md](../README.en.md) | English version |
| 变更日志 | [../CHANGELOG.md](../CHANGELOG.md) | 版本变更历史 |
| 贡献指南 | [../CONTRIBUTING.md](../CONTRIBUTING.md) | 代码规范、提交流程 |
| 行为准则 | [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | 社区行为准则 |
| 安全策略 | [../SECURITY.md](../SECURITY.md) | 安全漏洞上报 |
| 许可证 | [../LICENSE](../LICENSE) | MIT License |
| GitHub 模板 | [../.github/](../.github/) | Issue/PR 模板 |

---

## 🎯 按使用场景查找

### "我想..."

| 场景 | 文档 |
|:----|:----:|
| 我想快速启动项目 | [README](../README.md#-快速开始) |
| 我想搭建本地开发环境 | [dev-setup.md](dev-setup.md) |
| 我想知道代码规范 | [coding-standards.md](coding-standards.md) |
| 我遇到了报错 | [troubleshooting.md](troubleshooting.md) |
| 我想加一个新功能 | [git-workflow.md](git-workflow.md) + [coding-standards.md](coding-standards.md) |
| 我想了解系统架构 | [architecture.md](architecture.md) |
| 我想了解某个状态码含义 | [data-dictionary.md](data-dictionary.md) |
| 我想了解某个医疗术语 | [glossary.md](glossary.md) |
| 我想知道某个 API 的入参 | [apiDoc.md](apiDoc.md) |
| 我想知道表结构 | [databaseDoc.md](databaseDoc.md) |
| 我想部署到生产 | [deployDoc.md](deployDoc.md) |
| 我想监控系统状态 | [monitoring.md](monitoring.md) |
| 我想优化性能 | [performance.md](performance.md) |
| 我想发版 | [release-process.md](release-process.md) |
| 我想知道为什么用 FastAPI | [adr/0001](adr/0001-use-fastapi-instead-of-django.md) |
| 我想了解项目规划 | [todos.md](todos.md) |
| 我想报 Bug | [.github/ISSUE_TEMPLATE/bug_report.md](../.github/ISSUE_TEMPLATE/bug_report.md) |
| 我想提交 PR | [.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md) |

---

## 📐 文档维护约定

- **更新策略**：功能变更需同步更新对应文档
- **文档格式**：统一使用 Markdown（GFM 风格）
- **文档头部**：以"#"开头的一级标题作为文档标题
- **图表**：架构图/流程图统一放 `../doc_assets/` 目录
- **代码示例**：使用三反引号代码块，标注语言（`bash`、`python`、`js`、`vue`、`sql`）
- **链接**：相对路径引用，便于在线浏览
- **新增 ADR**：复制 [adr/template.md](adr/template.md) 创建

---

## 🆕 文档变更记录

| 日期 | 内容 |
|:----:|:-----|
| 2026-05-18 | 新增第三批：performance、monitoring、data-dictionary |
| 2026-05-18 | 新增第二批：git-workflow、release-process、glossary、ADR(5个)、CODE_OF_CONDUCT |
| 2026-05-18 | 新增第一批：dev-setup、coding-standards、testing、troubleshooting、GitHub 模板 |
| 2026-05-18 | 新增 architecture.md 架构文档与 doc/README.md 文档导航 |
| 2026-05-18 | 更新主 README.md：实际API数(247)、表数(61)、模块数(34) |
| 2026-05-17 | 新增 user-manual.md 用户操作手册 |
| 2026-05-17 | 更新 deployDoc.md 端口号说明 |
