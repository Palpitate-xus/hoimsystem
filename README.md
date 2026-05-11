# 医院门诊信息管理系统（HIS-OP）

[English](README.en.md) | **中文**

一个基于 Vue 3 + FastAPI 的医院门诊信息管理系统，覆盖挂号、就诊、收费、取药等门诊全流程。

---

## 功能特性

### 已实现的模块

| 模块 | 功能说明 | 状态 |
|:----:|:--------|:----:|
| 登录认证 | 用户注册/登录、bcrypt密码加密、JWT会话认证、角色权限控制 | ✅ |
| 病人管理 | 病人注册、信息查询、修改 | ✅ |
| 医生管理 | 医生注册、信息查询、修改、删除 | ✅ |
| 科室管理 | 科室创建、查询、修改、删除、主任设置 | ✅ |
| 挂号预约 | 现场挂号、预约挂号、取消、记录查询 | ✅ |
| 处方管理 | 医生开处方、库存校验与扣减、处方查询、取消 | ✅ |
| 收费管理 | 费用计算、在线缴费、退费、收费记录查询 | ✅ |
| 药品管理 | 药品入库、查询、修改、删除、库存查询 | ✅ |
| 通知公告 | 创建、查询、修改、删除、按角色定向推送 | ✅ |
| 病历管理 | 电子病历书写、修改、查询 | ✅ |
| 检查检验 | 检查申请、结果录入、审核、报告查看 | ✅ |
| 排队叫号 | 候诊队列、叫号、过号、跳号 | ✅ |
| 报到签到 | 预约报到转候诊队列 | ✅ |
| 药房发药 | 处方审核、发药确认、退药处理 | ✅ |
| 护士预检 | 生命体征录入、查询 | ✅ |
| 报表统计 | 门诊量、财务、药品、工作量统计 | ✅ |
| 随访管理 | 随访计划、复诊预约、随访记录 | ✅ |
| 满意度评价 | 就诊后评价、评分统计 | ✅ |
| 系统管理 | 操作日志审计、数据字典、系统参数配置 | ✅ |
| 消息中心 | 站内信/短信通知、消息列表、已读标记 | ✅ |
| 支付接口 | 微信/支付宝 Mock 支付、现金支付、支付流水 | ✅ |
| 智能导诊 | 症状描述→科室推荐（310+ 关键词匹配） | ✅ |
| 分诊台管理 | 四级分诊、科室推荐、候诊队列 | ✅ |
| 号源池管理 | 按科室统计号源分布 | ✅ |
| 数据备份恢复 | 手动备份、恢复、下载、删除 | ✅ |
| 权限分配 | 用户角色管理、密码重置、用户删除 | ✅ |
| 医生考勤 | 每日签到/签退、出勤统计 | ✅ |
| 违约处理 | 三次未取号暂停预约资格 | ✅ |
| 库存预警 | 低库存/近效期药品自动提醒 | ✅ |
| 处方点评 | 处方合理性审核记录 | ✅ |
| 日结对账 | 收费员每日收支汇总 | ✅ |
| 窗口挂号 | 收费员代病人现场挂号/退号 | ✅ |
| 耗材管理 | 医疗耗材入库、查询、修改、删除 | ✅ |
| 采购管理 | 采购订单创建、审批、入库、取消 | ✅ |
| ADR 监测 | 药品不良反应上报、跟踪 | ✅ |
| 不良事件上报 | 医疗安全事件记录、处理 | ✅ |
| CA 数字签名 | 电子签名、签名验证 | ✅ |
| 预交金管理 | 充值、查询、扣费 | ✅ |
| 双向转诊 | 门诊/住院/急诊转诊申请 | ✅ |
| MDT 会诊 | 多学科联合会诊申请、结果录入 | ✅ |
| 临床路径 | 临床路径方案管理 | ✅ |

### 规划中的模块

| 模块 | 功能说明 | 状态 |
|:----:|:--------|:----:|
| 医保接口 | 医保实时结算对接 | ⬜ |
| LIS/PACS 接口 | 检查检验系统数据交换 | ⬜ |

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层                                │
│                   vue3-new-ui                                │
│                   Vue 3 + Element-Plus                       │
├─────────────────────────────────────────────────────────────┤
│                        后端层                                │
│                    fastapi_be                                │
│              FastAPI + SQLAlchemy                            │
├─────────────────────────────────────────────────────────────┤
│                        数据层                                │
│                   MySQL / SQLite                             │
└─────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术 |
|:----:|:-----|
| 前端 | Vue 3, Element-Plus, Axios, Vuex |
| 后端 | FastAPI, SQLAlchemy, Pydantic, Alembic |
| 数据库 | PostgreSQL, SQLite（开发环境） |
| 容器化 | Docker, Docker Compose |
| CI/CD | GitHub Actions |
| 代码规范 | ruff (Python), Prettier (JavaScript) |
| 测试 | pytest (后端), Playwright (前端 E2E) |
| 安全 | RSA 密码传输加密, bcrypt 存储加密, JWT 会话认证 |

---

## 项目结构

```
hoimsystem/
├── vue3-new-ui/          # Vue 3 前端（当前主分支）
│   ├── src/
│   │   ├── views/        # 页面组件
│   │   ├── api/          # 接口封装
│   │   ├── router/       # 路由配置
│   │   └── store/        # Pinia状态管理
│   └── package.json
│
├── fastapi_be/           # FastAPI 后端（当前主分支）
│   ├── app/
│   │   ├── routers/      # 路由模块
│   │   │   ├── user.py        # 登录认证
│   │   │   ├── admin.py       # 管理员
│   │   │   ├── patient.py     # 病人
│   │   │   ├── doctor.py      # 医生
│   │   │   ├── pharmacy.py    # 药房
│   │   │   ├── charge.py      # 收费
│   │   │   ├── queue.py       # 排队叫号
│   │   │   ├── checkin.py     # 报到签到
│   │   │   ├── vitalsign.py   # 护士预检
│   │   │   ├── lab.py         # 检查检验
│   │   │   ├── followup.py    # 复诊随访
│   │   │   ├── report.py      # 报表统计
│   │   │   ├── system.py      # 系统管理
│   │   │   ├── triage.py      # 智能导诊
│   │   │   ├── backup.py      # 数据备份恢复
│   │   │   └── upload.py      # 文件上传
│   │   ├── models.py      # 数据库模型
│   │   ├── schemas.py     # Pydantic模型
│   │   ├── pagination.py  # 分页工具
│   │   └── main.py        # 应用入口
│   └── requirements.txt
│
├── doc/                  # 项目文档
│   ├── demandDoc.md      # 需求文档
│   ├── apiDoc.md         # API接口文档（146个接口，16个模块）
│   ├── databaseDoc.md    # 数据库文档（38张表）
│   ├── deployDoc.md      # 部署文档（开发/生产/Docker）
│   └── todos.md          # 待办事项
│
├── doc_assets/           # 文档资源（截图、流程图、SQL）
│
├── docker-compose.yml    # Docker Compose 编排
├── SECURITY.md           # 安全政策
├── CONTRIBUTING.md       # 贡献指南
├── CHANGELOG.md          # 更新日志
├── LICENSE               # MIT 许可证
│
├── .github/workflows/    # GitHub Actions CI/CD
│   └── ci.yml            # 后端测试 + 前端构建 + Docker 镜像
│
├── vue-ui/               # Vue 2.x 前端（已弃用，保留参考）
├── django_be/            # Django 后端（已弃用，保留参考）
│
└── README.md             # 本文件
```

---

## 快速开始

### 环境要求

- Node.js >= 16
- Python >= 3.10
- PostgreSQL >= 14（或使用 SQLite）

### 1. 克隆项目

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem
```

### 2. 启动数据库

```bash
# 创建 MySQL 数据库（或使用 SQLite）
mysql -u root -p -e "CREATE DATABASE hoimsystem CHARACTER SET utf8mb4;"
```

> 无需手动导入表结构，首次启动 FastAPI 后端时 SQLAlchemy 会自动建表。

### 3. 启动后端（FastAPI）

```bash
cd fastapi_be

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 运行（自动创建表）
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 启动前端（Vue 3）

```bash
cd vue3-new-ui

# 安装依赖
npm install

# 开发模式（Rspack）
npm run serve:rspack

# 生产构建
npm run build
```

### 5. Docker 一键启动（推荐）

```bash
# 启动 PostgreSQL + 后端 + 前端
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

### 6. 访问系统

- 前端：http://localhost:8091
- 后端 API：http://localhost:8000/api
- API 文档：http://localhost:8000/docs（FastAPI 自动生成的 Swagger UI）

---

## 系统角色

系统支持八种角色，覆盖门诊全岗位：

| 角色 | 权限范围 |
|:----:|:--------|
| 管理员 (admin) | 全局管理：医生、病人、科室、药品、通知、收费、系统配置 |
| 科室主任 (director) | 科室管理：本科室排班、医生管理、发布通知、处方点评 |
| 医生 (doctor) | 诊疗工作：病历书写、处方开立、检查申请、排班查看 |
| 护士 (nurse) | 护理工作：预检分诊、生命体征录入、排队叫号、随访管理 |
| 收费员 (cashier) | 收费窗口：现场挂号/退号、费用结算、日结对账 |
| 药师 (pharmacist) | 药房管理：处方审核、发药确认、退药处理、库存管理 |
| 导诊/挂号员 (guide) | 导诊服务：分诊台管理、智能导诊、候诊队列 |
| 病人 (patient) | 自助服务：挂号/预约、缴费、查看病历、满意度评价 |

---

## 文档索引

| 文档 | 说明 |
|:----:|:-----|
| [需求文档](doc/demandDoc.md) | 功能需求、业务流程、数据需求、非功能性需求 |
| [API 文档](doc/apiDoc.md) | 全部 143+ 个接口定义 |
| [数据库文档](doc/databaseDoc.md) | 25 张表结构定义及 ER 关系图 |
| [TODO](doc/todos.md) | 项目待办事项清单（按优先级分类） |

---

## 截图预览

![病人就医流程](doc_assets/PatientAccessFlow.png)

更多截图见 [doc_assets/](doc_assets/) 目录。

---

## 开发计划

详见 [doc/todos.md](doc/todos.md)。

近期重点：
1. ~~密码加密存储（bcrypt）~~ ✅ 已完成
2. ~~JWT Token 替换纯字符串 accessToken~~ ✅ 已完成
3. ~~接口权限校验细化~~ ✅ 已完成
4. ~~前端页面完善（数据修改/删除、报表统计）~~ ✅ 已完成
5. ~~库存预警机制~~ ✅ 已完成
6. ~~违约处理机制~~ ✅ 已完成
7. ~~数据备份与恢复~~ ✅ 已完成
8. ~~支付接口（微信/支付宝 Mock）~~ ✅ 已完成
9. ~~智能导诊~~ ✅ 已完成
10. ~~消息中心~~ ✅ 已完成
11. ~~权限分配~~ ✅ 已完成
12. ~~分诊台管理~~ ✅ 已完成
13. ~~号源池管理~~ ✅ 已完成
14. ~~医生考勤~~ ✅ 已完成
15. ~~日结对账~~ ✅ 已完成
16. ~~窗口挂号~~ ✅ 已完成
17. ~~耗材管理~~ ✅ 已完成
18. ~~采购管理~~ ✅ 已完成
19. ~~ADR 监测~~ ✅ 已完成
20. ~~不良事件上报~~ ✅ 已完成
21. ~~CA 数字签名~~ ✅ 已完成
22. ~~预交金管理~~ ✅ 已完成
23. ~~双向转诊~~ ✅ 已完成
24. ~~MDT 会诊~~ ✅ 已完成
25. ~~临床路径~~ ✅ 已完成
26. ~~前端页面美观性统一~~ ✅ 已完成
27. ~~依赖安全漏洞修复~~ ✅ 已完成
28. 医保接口对接

---

## 许可证

[MIT](LICENSE)

---

## 贡献

欢迎提交 Issue 和 Pull Request。

如有问题，请联系：palpitate.xus@outlook.com
