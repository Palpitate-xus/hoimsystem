# HIS-OP 前端验收测试报告

> 测试日期：2026-08-06  
> 测试范围：vue3-new-ui 前端、FastAPI 联调环境、用户手册与 RBAC 路由一致性

## 结论

当前版本不建议直接验收发布。管理员和患者的主要页面可以渲染，后端自动化用例全部通过；但前端生产构建被科研数据导出页阻断，操作日志页在现有 SQLite 数据库上返回 500，收费员岗位菜单与文档权限不一致。

## 执行结果

| 项目 | 结果 |
| --- | --- |
| 后端 pytest | 396 passed，4 skipped；1175.02 秒；2023 条 warning |
| 前端生产构建 | 失败：system/research.vue 导入不存在的 useUserStore |
| 前端静态分析 | 7 项：5 处 console、科研页缺少 empty-text、CSV 未本地化 |
| 管理员页面遍历 | 63 个路由中，除操作日志接口异常外均可渲染 |
| 患者预约页 | 使用实际账号 patient1/123456 可登录，页面正常显示 |
| RBAC E2E | 33 用例中 9 passed、24 failed；多数失败来自测试脚本 Hash 路由断言/严格定位器和文档账号与测试库不一致，不能直接作为产品失败数 |

## 问题清单

### P0：科研数据导出页导致整个前端构建失败

文件：vue3-new-ui/src/views/system/research.vue

该页执行 import { useUserStore } from "@/store"，但 src/store/index.js 只导出 Vuex 默认 store，没有 useUserStore named export。Rspack 输出 2 个 ESModulesLinkingError，导致正常构建产物不可交付。当前构建脚本仍可能以退出码 0 结束，CI 不能只依赖退出码判断成功。

### P0：操作日志页在现有 SQLite 库上必现 500

访问 POST /api/log/getList 时，后端查询 ORM 映射的 username 字段，但数据库表 hoimsystem_operation_log 仍只有旧字段：

log_id, user_id, action, target, result, ip, create_time

缺少 username、role、detail、status_code、method、path 等字段，后端日志明确报 sqlite3.OperationalError: no such column: hoimsystem_operation_log.username。这说明迁移未执行或测试库与当前模型版本不匹配。

### P1：收费员无法使用文档声明的岗位功能

用户手册声明 cashier 应能使用费用管理、发票管理、窗口挂号和日结对账；但 vue3-new-ui/src/router/index.js 中这些页面的权限主要是 admin/patient，没有 cashier。统计报表父菜单包含 cashier，子路由却只允许 admin/director。该问题会造成收费员登录后看不到自己的核心菜单。

### P1：文档账号与测试库不一致

文档写明患者 patient1/patient123，实测该密码无法登录，patient1/123456 才能登录。E2E 中的 doc01、director01、pharmacist01、cashier01 等账号也不在当前测试库中，导致批量角色测试失败。应统一初始化数据、文档和 E2E 固定账号。

### P2：医生首页请求无权限收费接口

医生登录后首页会请求 GET /api/chargeManagement/getList，后端返回 403，并在浏览器控制台记录“加载首页数据失败”。页面仍能显示，但属于不必要的越权请求和错误噪音，影响用户对系统状态的判断。

### P2：体检管理页默认查询返回 422

体检页调用 GET /api/examAppointment/getList?keyword=&status=，前端把空字符串 status 传给后端的 int 参数，后端返回 422。页面可能仍显示空表，但初次加载已经产生接口校验错误。

### P2：仓库内 E2E 测试存在误报

现有测试使用 Hash 路由，却断言 URL 不应包含 /login；登录后实际 URL 形如 /login#/index。部分断言未使用 .first()，在“首页”或错误消息存在多个 DOM 节点时触发 Playwright strict mode。测试还以 24 workers 并行共享 SQLite，放大了登录和数据竞争问题。

## 建议修复顺序

1. 修复科研页 store 导入并让构建脚本在 Rspack 有 errors 时返回非零。
2. 执行并校验 Alembic 迁移，重新生成与当前模型匹配的测试库；增加启动时 schema 检查。
3. 依据用户手册统一 cashier 等角色的前后端权限与测试账号。
4. 首页按角色加载允许的统计接口，移除医生无权请求。
5. 修正 E2E 的 Hash URL、严格定位器和 SQLite 并发策略后重新验收。
