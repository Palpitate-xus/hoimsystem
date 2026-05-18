# 系统架构文档

> 本文档介绍 HIS-OP 医院门诊信息管理系统的整体架构、技术选型理由、关键设计决策、模块划分及安全机制。
> 适合架构师、技术负责人、新加入团队的开发者阅读。

---

## 一、总体架构

### 1.1 架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                         浏览器 / 客户端                              │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTPS / HTTP
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Nginx 反向代理（生产）                          │
│           - 静态资源服务（前端 dist）                                 │
│           - /api/* 反向代理至 FastAPI                                │
│           - HTTPS 证书 / Gzip 压缩 / 静态缓存                         │
└────────────┬────────────────────────────────┬────────────────────┘
             │                                │
             ▼                                ▼
┌──────────────────────────┐    ┌───────────────────────────────────┐
│   前端 Vue 3 SPA          │    │     后端 FastAPI                   │
│   - Vue Router (Hash)    │    │   - 34 个路由模块                   │
│   - Vuex 状态管理         │    │   - 中间件链：                       │
│   - Element Plus 组件库   │    │     CORS / 日志 / 时间脱敏            │
│   - Axios 请求拦截         │    │   - JWT 鉴权                       │
│   - 69 个业务页面          │    │   - SQLAlchemy ORM                 │
└──────────────────────────┘    └────────────┬──────────────────────┘
                                              │
                                              ▼
                              ┌─────────────────────────────────────┐
                              │     数据库（SQLite/PostgreSQL）        │
                              │     61 张业务表，统一 hoimsystem_ 前缀  │
                              └─────────────────────────────────────┘
```

### 1.2 架构特点

- **前后端完全分离**：前端 SPA + 后端 REST API，独立部署、独立扩展
- **单体后端 + 模块化路由**：FastAPI 单进程承载 34 个业务模块，避免微服务的运维成本
- **数据库前缀隔离**：所有业务表统一以 `hoimsystem_` 为前缀，便于多系统共库部署
- **API 标准化**：所有接口走 `/api/` 前缀，统一鉴权头 `accesstoken`，统一响应结构 `{code, msg, data}`

---

## 二、技术选型

### 2.1 前端：Vue 3 + Element Plus

| 技术 | 版本 | 选型理由 |
|:----:|:----:|:--------|
| Vue 3 | 3.4+ | Composition API 更适合复杂业务；性能优于 Vue 2 |
| Element Plus | 2.x | 企业级中后台 UI 组件库，与医疗管理系统形态高度匹配 |
| Vue Router | 4.x | 与 Vue 3 配套；Hash 路由部署无需后端配合 |
| Vuex | 4.x | 比 Pinia 成熟稳定；满足用户/权限/标签页等全局状态 |
| Axios | 1.x | 拦截器机制方便统一加 token、错误处理 |
| Rspack | 1.x | 基于 Rust 的构建工具，启动/HMR 速度比 Webpack 快 10x+ |
| SCSS | - | 模板自带；支持 mixin/嵌套，比 CSS 高效 |

**为什么不选 React/Angular？**
- React 生态偏自由，中后台开发需要大量自选组件
- Angular 学习曲线陡，团队成员熟悉度低
- Vue 3 配合 Element Plus 是国内中后台事实标准

### 2.2 后端：FastAPI + SQLAlchemy

| 技术 | 版本 | 选型理由 |
|:----:|:----:|:--------|
| FastAPI | 0.111+ | 类型注解、自动文档、性能接近 Go，开发效率最高 |
| SQLAlchemy | 2.x | Python 最成熟的 ORM，2.x 全面拥抱类型注解 |
| Pydantic | 2.x | 与 FastAPI 配套；高性能数据校验 |
| Uvicorn/Gunicorn | latest | ASGI 服务器，生产用 Gunicorn + uvicorn worker |
| Alembic | latest | SQLAlchemy 配套的迁移工具 |
| PyJWT | latest | 标准 JWT 实现，社区主流 |
| bcrypt | latest | 密码哈希行业标准 |

**为什么不选 Django/Flask？**
- Django：自带 ORM 但前后端耦合重，REST 需要 DRF 加层
- Flask：轻量但缺少类型注解、自动文档，大型项目维护成本高
- FastAPI：性能 + 类型安全 + 自动文档（Swagger UI / ReDoc）三位一体

### 2.3 数据库：SQLite + PostgreSQL 双形态

| 环境 | 数据库 | 理由 |
|:----:|:------:|:----|
| 开发 | SQLite | 零配置启动，单文件、易备份、易重置 |
| 生产 | PostgreSQL | 并发性能、事务隔离、JSON 字段、扩展性 |

切换方式：仅需修改 `.env` 中的 `DATABASE_URL`，SQLAlchemy 自动适配。

**为什么不选 MySQL？**
- PostgreSQL 在医疗场景下的复杂查询、JSONB 字段、CTE/窗口函数更强
- 但 MySQL 也完全支持，只需切换 DATABASE_URL

---

## 三、目录结构与模块划分

### 3.1 后端模块组织

```
fastapi_be/app/
├── routers/             # 34 个路由模块，按业务域划分
├── models.py            # 61 张表的统一 SQLAlchemy 模型
├── schemas.py           # Pydantic 请求/响应模型
├── dependencies.py      # 依赖注入（JWT 解析、当前用户）
├── database.py          # 数据库连接、会话管理
├── config.py            # 配置加载（环境变量、.env）
├── pagination.py        # 分页工具
└── main.py              # 应用入口（中间件、CORS、路由注册）
```

**模块划分原则：**
- 一个业务领域一个 router 文件
- 跨模块共享的字段定义在 `models.py` 中集中维护
- 跨模块依赖的工具函数放 `dependencies.py` / `pagination.py`
- 不强行抽象 service 层（直接在 router 中操作 ORM，避免过度设计）

### 3.2 前端目录组织

```
vue3-new-ui/src/
├── views/             # 69 个页面，按业务域分子目录
│   ├── admin/         # 管理员（医生/病人/科室/通知/收费记录/号源池）
│   ├── patient/       # 患者（挂号/缴费/病历/处方/健康档案/...）
│   ├── doctor/        # 医生（排班/病历/处方/检查申请/考勤/MDT/路径）
│   ├── pharmacy/      # 药房（药品/审核/库存/采购/点评/耗材/ADR）
│   ├── charge/        # 收费（窗口挂号/费用/发票/日结）
│   ├── queue/         # 排队（分诊台/候诊队列/巡视）
│   ├── checkin/       # 报到（预约报到/违约记录）
│   ├── inpatient/     # 住院（床位/入院/医嘱/护士/费用/出院/手术/EMR）
│   ├── lab/           # 检验
│   ├── exam/          # 体检
│   ├── followup/      # 随访
│   ├── report/        # 报表统计
│   └── system/        # 系统（日志/字典/参数/备份/权限/...）
├── api/               # 按 router 对应的接口封装
├── router/            # 路由配置（按权限分组）
├── store/             # Vuex（user/permissions/tabsBar/settings）
└── styles/            # 全局样式（vab.scss 含统一工具类）
```

**前端组件复用约定：**
- `<vab-page-header>` — 统一页面头部（title + description）
- `.page-toolbar` — 页面顶部操作栏样式类
- `.pagination-wrapper` — 分页容器样式类
- `.form-full-width` — 表单元素 100% 宽度
- `.dialog-form` — 对话框表单统一样式

---

## 四、关键设计决策

### 4.1 鉴权方案：JWT + accesstoken 头

- **方案**：JWT 存储在前端 `localStorage`，每次请求通过 `accesstoken` 头携带
- **过期处理**：响应码 401 时前端清除 token 跳转登录
- **为什么不用 Cookie**：避免 CSRF 风险、便于跨域、便于客户端调试
- **为什么不用 OAuth**：内部系统不需要第三方授权，JWT 足够

### 4.2 时间字段微秒处理：中间件统一脱敏

- **问题**：SQLAlchemy 默认返回 datetime 包含微秒（`2026-05-18 14:30:45.123456`），前端展示丑陋
- **方案**：`StripMicrosecondMiddleware` 拦截所有 JSON 响应，正则替换微秒部分
- **位置**：[fastapi_be/app/main.py](../fastapi_be/app/main.py) 中的 `MICROSECOND_PATTERN`
- **优势**：业务代码无感知，统一处理

### 4.3 操作日志：中间件自动记录

- **方案**：`OperationLogMiddleware` 拦截所有 POST/PUT/DELETE 请求
- **解析逻辑**：
  - 从 `accesstoken` 解析 user_id
  - 路径如 `/api/patientManagement/update` → 自动映射为 "更新·患者"
  - 根据 HTTP 状态码记录 "成功" / "失败"
  - 从 `X-Forwarded-For` 获取真实客户端 IP
- **跳过列表**：列表查询接口不记录，避免日志爆炸
- **优势**：业务代码零侵入，全量审计覆盖

### 4.4 身份证号脱敏

- **场景**：所有显示给用户的页面（患者管理表格、健康档案）
- **方案**：前端 `maskIdentity()` 函数显示为 `370101********1234`
- **不脱敏的场景**：用户输入身份证号（注册、检索）、检验/检查报告归档
- **未来增强**：可移至后端按角色返回脱敏/原文

### 4.5 SQLite 与 PostgreSQL 兼容

- **方案**：所有 SQL 通过 SQLAlchemy ORM 表达，避免数据库特有语法
- **特殊处理**：分页用 `offset/limit`；ID 主键用 `Integer + autoincrement`
- **JSON 字段**：跨数据库统一用 `String` 存 JSON 字符串，前端 `JSON.parse`
- **切换成本**：仅需修改 `.env` 中的 `DATABASE_URL` 即可

### 4.6 前端路由组织：按业务域 + 权限

- **路由分组**：menu 按 `permissions` 数组控制可见性
- **示例**：
  ```js
  meta: { title: "医生工作站", permissions: ["doctor", "director"] }
  ```
- **运行时过滤**：`store/routes.js` 根据当前用户权限过滤可见菜单
- **前后端双重校验**：前端隐藏菜单 + 后端接口校验权限，两层防护

### 4.7 三步式业务流程优化

- **场景**：现场挂号、报到签到、双向转诊原本要求用户手动输入 ID
- **改造**：统一改为三步流程
  1. **第一步**：输入身份证号
  2. **第二步**：选择可用项（如号源卡片）
  3. **第三步**：成功反馈
- **优势**：避免用户接触 ID，提升易用性，减少出错

---

## 五、数据流示例

### 5.1 患者预约挂号流程

```
[患者] ──登录──> [前端] ──/api/login──> [后端] ──校验bcrypt密码──> [DB]
                                              └──返回 JWT token

[患者] ──查询号源──> [前端] ──/api/appointmentManagement/appointmentList──> [后端]
                                                       └──SELECT DoctorSchedule──> [DB]

[患者] ──下单──> [前端] ──/api/appointmentManagement/create──> [后端]
                                              ├──检查违约记录（30天内3次则禁用）
                                              ├──检查号源余量
                                              ├──INSERT Appointment──> [DB]
                                              └──UPDATE DoctorSchedule.number--
                       └──[中间件] 自动写入操作日志（新增·预约）

[患者] ──报到──> [前端] ──/api/checkIn/getAppointments(身份证)──> [后端]
                                              └──SELECT 当天待报到的预约
[患者] ──选择卡片──> [前端] ──/api/checkIn/checkIn(uuid, identity)──> [后端]
                                              ├──INSERT Queue（生成队列号）
                                              ├──UPDATE Appointment.status=已报到
                                              └──返回队列号 + 候诊位置
```

### 5.2 医生工作站完整诊疗流程

```
[医生] ──签到──> [/api/attendance/checkIn]
[医生] ──呼叫下一位──> [/api/queue/callNext] ──> 候诊队列移除
[医生] ──写病历──> [/api/medicalRecordManagement/create] ──> 结构化病历
[医生] ──开处方──> [/api/prescriptionManagement/create]
              ├──校验药品库存
              ├──INSERT Prescription + Pre_pha 明细
              └──生成待审核处方
[医生] ──开检查──> [/api/labOrder/create] ──> 生成检验申请单
[患者] ──缴费──> [/api/charge/pay] ──> 状态变为"待发药/检查"
[药师] ──审核处方──> [/api/pharmacy/audit] ──> 状态变为"待发药"
[药师] ──发药──> [/api/pharmacy/dispense] ──> 扣减库存，发药完成
```

---

## 六、安全机制

### 6.1 认证与授权

| 机制 | 实现 |
|:----:|:----|
| 密码加密 | bcrypt（cost=12），不可逆 |
| 会话管理 | JWT（HS256），24 小时过期 |
| 接口鉴权 | `Depends(get_current_user)` 校验 token |
| 角色权限 | 用户表 `user_role` 字段，前端菜单 + 后端接口双重校验 |

### 6.2 数据安全

| 机制 | 实现 |
|:----:|:----|
| 身份证号显示 | 前端 `maskIdentity()` 脱敏（370101********1234） |
| 操作审计 | 中间件自动记录所有 POST/PUT/DELETE 操作 |
| SQL 注入防护 | 全部走 SQLAlchemy ORM，参数化查询 |
| XSS 防护 | Vue 默认 HTML 转义；Element Plus 组件无 v-html 漏洞 |
| CORS | 后端中间件白名单（生产环境需限制为前端域名） |

### 6.3 部署安全

- 生产环境 `.env` 中 **必须**：
  - `SECRET_KEY` 设置为随机 32 字节
  - `DATABASE_URL` 不能使用默认 SQLite
  - 移除调试日志、关闭 `--reload`
- Nginx 配置 HTTPS（Let's Encrypt 免费证书）
- 限制后端只监听 `127.0.0.1`，由 Nginx 反向代理

---

## 七、性能考虑

### 7.1 当前性能

- **数据库**：SQLite 单进程 < 1000 并发够用；PostgreSQL 可支持万级并发
- **API 响应**：90% 接口 < 50ms（SQLite 本地查询）
- **前端首屏**：未压缩约 2-3 MB，gzip 后 < 800KB

### 7.2 优化空间

| 短板 | 优化方向 |
|:----:|:--------|
| 列表查询无分页 | 患者/医生/药品列表已加，少数列表待补 |
| 报表实时查询 | 可加缓存层（Redis）+ 离线计算 |
| 前端 bundle 大 | 路由懒加载（已加），可进一步拆 vendor |
| 操作日志增长快 | 可加分区表 / 定期归档 |

---

## 八、与主流 HIS 的差距

详细对标分析见用户对话历史。简要总结：

| 维度 | 覆盖率 |
|:----:|:------:|
| HIS 核心模块 | 65% |
| 临床应用完整性 | 55% |
| 集成对接能力（医保/PACS/HL7） | **20%（最大短板）** |
| 互联网/移动化 | 10% |
| 合规与安全（三级等保） | 30% |

**关键缺失**：
- 🔴 医保接口（无医保无法用于真实生产）
- 🔴 PACS/影像系统
- 🔴 闭环医嘱 + CDSS 合理用药
- 🟠 DRG/DIP 病案首页
- 🟠 输血/院感/PIVAS 等专科子系统

**当前定位**：适合中小诊所、教学/演示、HIS 二次开发起点。

---

## 九、开发指南

### 9.1 新增一个 API

```python
# 1. 在 fastapi_be/app/routers/your_module.py 中定义路由
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter()

@router.post("/yourModule/create")
def create_xxx(req: YourSchema, db: Session = Depends(get_db)):
    ...
    return {"code": 200, "msg": "success"}

# 2. 在 fastapi_be/app/main.py 注册路由
app.include_router(your_module.router, prefix="/api")

# 3. 在 vue3-new-ui/src/api/your_module.js 添加前端调用
export function createYourThing(data) {
  return request({ url: "yourModule/create", method: "post", data });
}
```

### 9.2 新增一张数据表

```python
# 1. 在 fastapi_be/app/models.py 添加模型
class YourModel(Base):
    __tablename__ = "hoimsystem_your_table"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ...

# 2. 重启后端，SQLAlchemy 自动创建表
# 3. （生产环境）使用 Alembic 生成迁移脚本
alembic revision --autogenerate -m "add your_table"
alembic upgrade head
```

### 9.3 新增一个前端页面

```bash
# 1. 在 vue3-new-ui/src/views/{module}/ 下创建 .vue 文件
# 2. 使用统一模板：

<template>
  <div class="app-container">
    <vab-page-header title="页面标题" description="功能描述" />
    <el-card>
      <div class="page-toolbar">...</div>
      <el-table empty-text="暂无数据" v-loading="loading">...</el-table>
      <el-pagination class="pagination-wrapper" />
    </el-card>
  </div>
</template>

# 3. 在 vue3-new-ui/src/router/index.js 注册路由
{
  path: "yourPage",
  component: () => import("@/views/{module}/yourPage.vue"),
  meta: { title: "页面标题", permissions: ["doctor"] }
}
```

---

## 十、参考资料

- [Vue 3 官方文档](https://vuejs.org/)
- [Element Plus 文档](https://element-plus.org/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.x 文档](https://docs.sqlalchemy.org/)
- 卫健委：《医院信息系统基本功能规范》
- 卫健委：《电子病历系统功能规范（试行）》
