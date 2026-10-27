# 文档总览

HOIM 医院信息管理系统的使用、开发与部署文档。可按使用场景或岗位查找操作步骤、接口、数据模型和维护指南。

AI 平台包含 80 项能力、业务工作台及超级管理员管理中心，配置步骤、Prompt 和测试记录见 AI 平台导航。

---

## 📚 文档导航

### AI 平台

| 文档 | 内容 |
| --- | --- |
| [开发与使用指南](ai-guide.md) | 工作台、41 个超管入口、模型/知识/来源配置及启用步骤 |
| [80 项能力清单](ai-capabilities.md) | 功能、资料范围、输入输出与默认角色 |
| [完整默认 Prompt](ai-prompts.json) | 默认任务文本、目录版本和固定系统契约 |
| [实施记录](ai-implementation-plan.md) | 各功能交付过程、变更和验证范围 |
| [全部80项集成验证](ai-final-integration-verification.json) | 工程接入的历史验收、失败轮及完整文件复验 |
| [Prompt与界面体验验证](ai-experience-verification.json) | 2026-10-26 默认Prompt、文书复制、管理导航及业务面板优化验证 |
| [系统功能、AI与性能验证](validation/2026-10-27/README.md) | 2026-10-27 全量回归、模拟/真实服务、事务竞争、分级负载及修复证据 |
| [qSOFA/GCS专题验证](ai-qsofa-verification.json) | 独立风险规则与来源核对的专题记录 |

首次使用从开发与使用指南开始，输入输出按能力清单查询，测试与构建结果按专题查阅。

### 📘 软件与业务文档

1. **[软件说明书](software-manual.md)** — 软件概述/运行环境/功能结构/角色权限/数据与安全总览
2. **[安装部署手册](installation-guide.md)** — 生产部署步骤/备份策略/升级发布/故障排查
3. **[业务流程图](flowcharts/README.md)** — 8 组 58 张 Mermaid 流程图覆盖全部业务域
4. **[业务逻辑测试报告](business-test-report.md)** — 业务场景、测试结果、规则核对与修复记录
5. **[HIS 功能完整性盘点](his-feature-gap-analysis.md)** — 对照标准 HIS 产品的 15 方向缺口分析与建设排序
6. **[安全上线清单](security-launch-checklist.md)** — 账号、鉴权、日志和基础设施配置核对

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
5. **[路线图](todos.md)** — 功能清单与项目规划

### 💻 后端开发

1. **[编码规范](coding-standards.md)** — Python/Vue/数据库/Git 全规范
2. **[API 文档](apiDoc.md)** — 核心模块接口的入参、响应、错误码（当前 1,087 个 RBAC 路由方法的角色权限见 [api-rbac-matrix.md](api-rbac-matrix.md)）
   - **[API 测试报告](api-test-report.md)** — 接口测试场景与结果记录
3. **[数据库文档](databaseDoc.md)** — 核心表字段说明（当前 266 个 ORM 表定义分布于 `fastapi_be/app/models.py`、AI 及住院扩展模型中，以源码与迁移为准）
4. **[数据字典](data-dictionary.md)** — 状态码、枚举值统一定义
5. **[架构文档](architecture.md)** — 中间件、依赖、安全机制
6. **[测试指南](testing.md)** — pytest 测试编写与运行
7. **[LIS/PACS/医保对接指南](integration-guide.md)** — 入站鉴权、幂等回调和厂商联调边界
8. **[院内导航配置指南](navigation-guide.md)** — 节点、路线连线与患者端最短路径
9. **[等保安全基线自评](security-baseline-checklist.md)** — 本地安全证据与测评前置事项
10. **[移动 Web 使用说明](mobile-web-guide.md)** — PWA 安装、缓存边界和原生端规划
11. **[监控与运维](monitoring.md)** — 存活/就绪探针、Prometheus 指标、调度与故障处置

### 🎨 前端开发

1. **[前端 README](../vue3-new-ui/README.md)** / **[English](../vue3-new-ui/README.en.md)** — 启动、API 配置、AI 页面、构建与测试命令
2. **[编码规范](coding-standards.md)** — Vue 3 组件规范、样式工具类
3. **[API 文档](apiDoc.md)** — 后端接口规范
4. **[用户操作手册](user-manual.md)** — 各页面的业务流程
5. **[架构文档](architecture.md)** — 前端目录约定与组件复用
6. **[测试指南](testing.md)** — 前端组件与 Playwright 测试
   - **[前端页面测试报告](frontend-test-report.md)** — 页面审查与测试记录

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
| 2026-10-27 | 按项目功能和使用流程更新中英文主 README，重写前端中英文 README，补充数据库初始化与接管说明、AI 导航，并同步路线图中的 AI 与 DRG 状态；核对 134 个路由模块、1,087 个 RBAC 路由方法、266 个表定义和 160 个页面 |
| 2026-09-03 | 同步 560 个路由方法、145 张表及可观测性、实时事件、集成发件箱、eMAR、CDSS、DRG/DIP 和 PostgreSQL 基准文档 |
| 2026-05-18 | 新增第三批：performance、monitoring、data-dictionary |
| 2026-05-18 | 新增第二批：git-workflow、release-process、glossary、ADR(5个)、CODE_OF_CONDUCT |
| 2026-05-18 | 新增第一批：dev-setup、coding-standards、testing、troubleshooting、GitHub 模板 |
| 2026-05-18 | 新增 architecture.md 架构文档与 doc/README.md 文档导航 |
| 2026-05-18 | 更新主 README.md：实际API数(247)、表数(61)、模块数(34)（历史值，后续以各文档当前值为准） |
| 2026-05-17 | 新增 user-manual.md 用户操作手册 |
| 2026-05-17 | 更新 deployDoc.md 端口号说明 |
