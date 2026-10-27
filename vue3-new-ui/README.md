# HOIM 前端

**中文** | [English](README.en.md)

HOIM 医院信息管理系统的 Web 前端，位于 [hoimsystem](https://github.com/Palpitate-xus/hoimsystem) 仓库的 `vue3-new-ui/` 目录，与 `fastapi_be/` 中的 FastAPI 后端配合使用。

页面覆盖门诊挂号与医生工作站、住院与护理、药房药库、检查检验、体检、收费、患者服务、运营报表和系统管理。菜单与操作根据登录角色和业务权限展示。

## 技术栈与目录

| 用途 | 技术 |
| --- | --- |
| 页面与组件 | Vue 3.5、Element Plus 2、Sass |
| 路由与状态 | Vue Router 5、Vuex 4 |
| 接口与图表 | Axios、ECharts 6 |
| 开发与构建 | Rspack 2、Vue Loader、Babel |
| 测试 | Node.js 内置测试运行器、Playwright |

具体依赖版本及命令见 [package.json](package.json)，安装版本由 [package-lock.json](package-lock.json) 记录。

```text
vue3-new-ui/
├── src/
│   ├── views/          # 按业务划分的页面，含 AI 工作台与管理中心
│   ├── components/     # 业务组件、共享助手及各领域 AI 面板
│   ├── api/            # 接口封装与来源、结果契约
│   ├── router/         # 路由与角色元数据
│   ├── store/          # 登录会话和页面状态
│   ├── config/         # 标题、端口、接口等配置
│   └── styles/         # 公共样式
├── layouts/            # 页面布局
├── public/             # HTML 模板与静态文件
├── tests/              # Node.js 测试
├── scripts/            # 构建检查、数据生成及 Node.js 测试
├── e2e/                # Playwright 用例与隔离测试夹具
└── rspack.config.js    # 构建、开发服务与代理配置
```

## 本地启动

使用符合 `^20.19.0 || >=22.12.0` 的 Node.js 和 npm 10 或以上版本。

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem/vue3-new-ui
npm ci --legacy-peer-deps
npm run serve:rspack
```

访问 <http://localhost:8091>。后端环境、数据库迁移与 API 启动步骤见[项目说明](../README.md)和[部署手册](../doc/installation-guide.md)。AI 异步任务由后端独立 worker 处理，启动步骤见 [AI 使用指南](../doc/ai-guide.md)。

### 端口与 API 配置

| 配置 | 当前值与位置 |
| --- | --- |
| 开发端口 | [setting.config.js](src/config/setting.config.js) 的 `devPort: "8091"`，由 Rspack 开发服务使用 |
| 路由模式 | 同文件中的 `routerMode: "hash"` |
| API 前缀 | [net.config.js](src/config/net.config.js) 的 `baseURL: "/api"`，开发和生产均使用此值 |
| 开发代理 | [rspack.config.js](rspack.config.js) 的 `devServer.proxy` 将 `/api` 请求转发到 `http://localhost:8000`，保留原路径 |
| 构建输出 | `setting.config.js` 的 `outputDir: "dist"` |

连接其他后端时，修改开发代理的 `target`；修改本地端口时，调整 `devPort`。生产环境将 `dist/` 交给静态 Web 服务，并为同源 `/api` 配置后端反向代理。部署示例见[部署手册](../doc/installation-guide.md)。

开发 Mock 通过命令行显式开启：

```bash
VUE_APP_MOCK_ENABLE=true npm run serve:rspack
```

该开关由 [rspack.js](rspack.js) 和开发服务中间件读取，默认值为 `false`。日常联调使用默认启动命令连接 FastAPI。

## AI 工作台与业务入口

| 入口 | 用法 |
| --- | --- |
| `/#/ai/workbench` | AI 业务助手：选择当前有权使用的能力、患者或业务范围，核对资料后提交任务，查看结果、依据与复核反馈 |
| `/#/ai/manage` | AI 管理中心：由 `super_admin` 超级管理员配置功能、模型、Prompt、知识、来源与授权，并查看任务、用量和审计 |
| 业务记录行 | 病历“检查病历”、处方“核查处方”、药房“核查用药”、手术“术前评估”等入口，携带当前记录及患者、就诊范围 |
| 运营与资料页面 | 床位、库存、运营报表、说明书及科研等页面提供相应来源的选择、核对和分析入口 |

[80 项能力目录](../doc/ai-capabilities.md)涵盖文本整理与诊疗参考、文书草稿、用药核查、患者沟通、语音、影像、心电、风险规则、运营预测、科研及教学等任务。具体任务按角色、功能配置和当前资料用途提供，结果页展示依据、资料缺口与人工复核事项。

### 超级管理员管理

管理中心保留 41 个入口，按四组组织，可通过“查找管理入口”搜索：

| 分组 | 管理内容 |
| --- | --- |
| 功能与模型 | 能力启用、角色与额度、Prompt 版本、文本模型和专用服务 |
| 知识与数据 | 知识审核、临床与运营来源、说明书、科研、运维、教学及其他领域资料治理 |
| 任务与用量 | 全局技术任务、任务与反馈、调用统计 |
| 权限与审计 | 患者访问授权、配置审计、反馈脱敏审核 |

使用时先配置实际模型服务与用途范围，再准备并审核知识或领域来源，在“能力与启用”中选择角色、模型、Prompt、额度和验证记录后启用。来源目录、发布件和任务正文按各自权限核对。详细步骤见 [AI 使用指南](../doc/ai-guide.md)。

### 文书栏目复核与复制

门诊病历、入院记录、病程、出院小结和影像报告草稿将“文书正文”与摘要、警示、资料缺口分开呈现。点击“复制文书正文”后，选择栏目并逐项核对；存在警示或缺项时，确认已复核再复制。剪贴板保留所选栏目的原文及顺序，后续编辑、签名和业务提交由原业务页面完成。

教学入口按“选择课程 → 作答并提交 → 查看成绩与解析 → 获取 AI 讲解”使用；固定成绩与模型反馈分别展示。

## 构建与检查

以下命令均在 `vue3-new-ui/` 中执行：

| 命令 | 用途 |
| --- | --- |
| `npm run serve:rspack` | 启动开发服务 |
| `npm run build` | 重新生成 `dist/` 生产资源 |
| `npm run audit` | 按 `low` 等级执行 npm 依赖审计 |
| `npm run check:bundle` | 检查已有 `dist/` 的单个 JS、JS 总量和总资源大小预算 |
| `npm run verify` | 依次执行依赖审计、生产构建和资源预算检查 |
| `npm run build:zip` | 构建并生成 `dist/dist.zip` |
| `npm run test:e2e -- <用例路径>` | 运行指定 Playwright 用例 |

Node.js 测试位于 `tests/` 和 `scripts/`，可以按文件运行，也可以执行两处测试集合：

```bash
node --test tests/aiManagementNavigation.test.cjs scripts/ai-document-draft.test.cjs
node --test tests/*.test.cjs scripts/*.test.cjs
```

Playwright 配置见 [playwright.config.js](playwright.config.js)。先安装 Chromium，再按修改范围选择用例：

```bash
npx playwright install chromium
npm run test:e2e -- --list
npm run test:e2e -- e2e/ai-management-navigation.spec.js --workers=1
```

部分用例使用夹具启动隔离页面；访问完整应用的用例使用 `E2E_BASE_URL`，默认地址为 `http://localhost:8091`。这类用例运行前先启动前端，或指向已提供构建资源的服务，例如：

```bash
E2E_BASE_URL=http://localhost:8091 npm run test:e2e -- e2e/ai-workbench.spec.js --workers=1
npx playwright show-report
```

## 相关文档与来源

- [项目说明与后端启动](../README.md)
- [AI 使用与配置指南](../doc/ai-guide.md)
- [AI 能力目录](../doc/ai-capabilities.md)
- [部署手册](../doc/installation-guide.md)

前端布局基础源自 [Vue Admin Better](https://github.com/zxwk1998/vue-admin-better)，在此基础上实现 HOIM 医院业务与 AI 平台。保留上游 MIT 许可和版权声明，见本目录的 [LICENSE](LICENSE)。
