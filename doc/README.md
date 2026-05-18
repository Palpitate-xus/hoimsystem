# 文档总览

> 本目录包含 HIS-OP 医院门诊信息管理系统的全部技术文档。
> 不同角色可按下方导航直达对应文档。

---

## 📚 文档导航

### 🆕 新人快速上手

1. **[项目主 README](../README.md)** — 项目概览、技术栈、快速启动
2. **[部署文档](deployDoc.md)** — 本地开发环境与生产部署
3. **[用户手册](user-manual.md)** — 各角色的具体操作流程

### 🏗 架构师 / 技术负责人

1. **[架构文档](architecture.md)** — 系统架构、技术选型、设计决策
2. **[需求文档](demandDoc.md)** — 业务需求与非功能需求
3. **[路线图](todos.md)** — 已完成功能与未来规划

### 💻 后端开发

1. **[API 文档](apiDoc.md)** — 247 个接口的入参、响应、错误码
2. **[数据库文档](databaseDoc.md)** — 61 张表的字段、索引、ER 关系
3. **[架构文档](architecture.md)** — 中间件、依赖、安全机制

### 🎨 前端开发

1. **[API 文档](apiDoc.md)** — 后端接口规范
2. **[用户手册](user-manual.md)** — 各页面的业务流程
3. **[架构文档](architecture.md)** — 前端目录约定与组件复用

### 🚀 运维 / DevOps

1. **[部署文档](deployDoc.md)** — Docker、Nginx、Systemd、HTTPS、Alembic
2. **[安全策略](../SECURITY.md)** — 安全漏洞上报流程

### 👥 业务方 / 测试

1. **[需求文档](demandDoc.md)** — 业务场景描述
2. **[用户手册](user-manual.md)** — 操作步骤与示例

---

## 📋 文档清单

| 文件 | 说明 | 主要受众 | 行数估计 |
|:----:|:-----|:--------:|:-------:|
| [architecture.md](architecture.md) | 架构与技术选型 | 架构师、技术负责人 | ~400 |
| [demandDoc.md](demandDoc.md) | 需求文档 | 业务、测试、架构师 | ~1100 |
| [apiDoc.md](apiDoc.md) | API 接口文档 | 前后端开发 | ~1500 |
| [databaseDoc.md](databaseDoc.md) | 数据库设计文档 | 后端开发、DBA | ~800 |
| [deployDoc.md](deployDoc.md) | 部署文档 | 运维、新人 | ~280 |
| [user-manual.md](user-manual.md) | 用户操作手册 | 业务方、测试、培训 | ~650 |
| [todos.md](todos.md) | 待办与路线图 | 全员 | ~800 |

---

## 🔗 项目其他文档

| 文件 | 位置 | 说明 |
|:----:|:----:|:-----|
| 主 README | [../README.md](../README.md) | 项目入口 |
| 英文 README | [../README.en.md](../README.en.md) | English version |
| 变更日志 | [../CHANGELOG.md](../CHANGELOG.md) | 版本变更历史 |
| 贡献指南 | [../CONTRIBUTING.md](../CONTRIBUTING.md) | 代码规范、提交流程 |
| 安全策略 | [../SECURITY.md](../SECURITY.md) | 安全漏洞上报 |
| 许可证 | [../LICENSE](../LICENSE) | MIT License |

---

## 📐 文档维护约定

- **更新策略**：功能变更需同步更新对应文档
- **文档格式**：统一使用 Markdown（GFM 风格）
- **文档头部**：以"#"开头的一级标题作为文档标题
- **图表**：架构图/流程图统一放 `../doc_assets/` 目录
- **代码示例**：使用三反引号代码块，标注语言（`bash`、`python`、`js`、`vue`、`sql`）
- **链接**：相对路径引用，便于在线浏览

---

## 🆕 文档变更记录

| 日期 | 内容 |
|:----:|:-----|
| 2026-05-18 | 新增 architecture.md 架构文档与 doc/README.md 文档导航 |
| 2026-05-18 | 更新主 README.md：实际API数(247)、表数(61)、模块数(34) |
| 2026-05-17 | 新增 user-manual.md 用户操作手册 |
| 2026-05-17 | 更新 deployDoc.md 端口号说明 |
