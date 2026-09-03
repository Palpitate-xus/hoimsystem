# 医院门诊信息管理系统（HIS-OP）

[English](README.en.md) | **中文**

基于 **Vue 3 + FastAPI** 的中小型医院综合信息管理系统，覆盖 **门诊、住院、药房、检验、体检、收费** 等核心业务全流程。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vue](https://img.shields.io/badge/Vue-3.x-4FC08D)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-009688)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)

---

## 📊 项目规模

| 维度 | 数量 |
|:----:|:----:|
| 业务模块 | **75** 个后端路由模块 |
| API 接口 | **541** 个 RESTful 接口 |
| 数据库表 | **139** 张业务表 |
| 前端页面 | **143** 个 Vue 页面 |
| 用户角色 | **8** 种（admin/director/doctor/nurse/cashier/pharmacist/guide/patient） |

---

## 🌟 功能特性

### 已实现的核心业务（9 大领域 / 40+ 模块）

#### 1️⃣ 门诊管理
| 模块 | 功能说明 |
|:----:|:--------|
| 智能导诊 | 症状描述→科室推荐（310+ 关键词匹配） |
| 分诊台 | 4 级分级导诊、科室分流 |
| 预约挂号 | 在线预约、按医生/科室、专家号区分 |
| 现场挂号 | 患者自助/窗口代办两种模式 |
| 报到签到 | 三步式扫码报到（身份证→选预约→生成队列号） |
| 排队叫号 | 候诊队列、叫号、过号、跳号、急诊插队 |
| 候诊巡视 | 巡视记录、关注高风险患者 |
| 违约记录 | 三次违约自动暂停预约 30 天 |
| 缴费管理 | 待缴清单、在线/窗口缴费、退费 |
| 收费记录 | 收费流水、状态跟踪、明细查询 |
| 发票管理 | 发票开具、查询、作废 |
| 日结对账 | 收费员每日收支汇总 |

#### 2️⃣ 医生工作站
| 模块 | 功能说明 |
|:----:|:--------|
| 排班管理 | 医生周排班、号源数量、专家标记 |
| 电子病历 | 主诉/现病史/既往史/诊断/治疗，模板复用 |
| 处方开立 | 药品搜索、剂量频次途径、库存校验 |
| 检查检验申请 | 检查类型、项目、紧急标记 |
| 考勤签到 | 每日签到/签退、出勤统计 |
| 多学科会诊 | MDT 申请、参与科室、结果录入 |
| 临床路径 | 路径模板管理、进度跟踪 |

#### 3️⃣ 药房药库
| 模块 | 功能说明 |
|:----:|:--------|
| 药品管理 | 入库、查询、修改、库存查询 |
| 耗材管理 | 医疗耗材入库、查询、修改、删除 |
| 处方审核 | 药师审方、确认发药 |
| 发药管理 | 处方核对、发药确认、退药 |
| 库存预警 | 低库存/近效期自动提醒 |
| 库存盘点 | 实物盘点、差异处理 |
| 药品采购 | 采购订单、审批、入库 |
| 处方点评 | 合理性审核、问题统计 |
| ADR 监测 | 药品不良反应上报、跟踪 |

#### 4️⃣ 住院管理
| 模块 | 功能说明 |
|:----:|:--------|
| 病区床位 | 病区维护、床位状态、空床查询 |
| 入院登记 | 4 种入院类型、床位分配、押金登记 |
| 住院医嘱 | 长期/临时医嘱、审核、停止、撤销 |
| 护士工作站 | 医嘱执行、护理记录、体温录入 |
| 住院费用 | 费用明细、每日清单、押金扣减 |
| 出院结算 | 总费用计算、押金退还 |

#### 5️⃣ 电子病历（EMR）
| 模块 | 功能说明 |
|:----:|:--------|
| 病历模板 | 病种模板、复用 |
| 结构化病历 | 主诉/现病史/既往史/查体/诊断/治疗 |
| 病程记录 | 日常病程、上级查房 |
| 查房记录 | 主任/副主任查房、查房意见 |
| 病历质控 | 三级签名、归档 |
| CA 数字签名 | 电子签名、签名验证 |

#### 6️⃣ 检验科 / 体检
| 模块 | 功能说明 |
|:----:|:--------|
| 检查检验 | 申请、样本接收、结果录入、审核 |
| 检验结果查询 | 结果列表、异常标记、报告查看 |
| 体检套餐 | 套餐定义、项目组合 |
| 体检预约 | 在线预约、状态跟踪 |
| 体检记录 | 检查录入、结果汇总 |
| 体检报告 | 报告生成、综合评估 |

#### 7️⃣ 手术管理
| 模块 | 功能说明 |
|:----:|:--------|
| 手术申请 | 急诊/择期、麻醉方式 |
| 手术排台 | 主刀/麻醉医师分配、时间安排 |
| 麻醉记录 | 麻醉过程、用药记录 |

#### 8️⃣ 患者服务
| 模块 | 功能说明 |
|:----:|:--------|
| 健康档案 | 个人信息、过敏史、就诊记录 |
| 病历查询 | 历次就诊病历查看 |
| 处方查询 | 处方明细、状态 |
| 预交金管理 | 充值、查询、扣费、退款 |
| 双向转诊 | 门诊/住院/急诊转诊 |
| 复诊随访 | 随访计划、患者反馈、随访记录 |
| 满意度评价 | 就诊评价、评分统计 |

#### 9️⃣ 系统平台
| 模块 | 功能说明 |
|:----:|:--------|
| 用户权限 | 角色管理、密码重置、用户删除 |
| 操作日志 | 全量操作审计、按用户/操作筛选（中间件自动记录） |
| 数据字典 | 业务字典维护 |
| 系统参数 | 配置项管理 |
| 消息中心 | 站内信、已读标记 |
| 通知公告 | 按角色定向推送 |
| 数据备份 | 手动备份、恢复、下载 |
| 不良事件 | 医疗安全事件记录 + RCA 根因分析（PDCA 闭环） |
| 号源池 | 按科室统计号源分布 |
| 报表统计 | 门诊量/收费/药品/工作量 4 大类报表 + 科室绩效核算 |
| MDRO 隔离 | 耐药菌隔离登记/解除、床头标识 |
| 传染病报告卡 | 法定病种自动判类、网直上报状态机（待报→上报→审核→订正） |
| HQMS 指标 | 质量指标录入/导入/批量上报 |

#### 🔟 HIS 补齐模块（2026-08 四批交付，零预置数据、全手工录入/批量导入）
| 模块 | 功能说明 |
|:----:|:--------|
| 审方规则引擎 | 药师维护配伍/禁忌/剂量/重复/过敏 5 类规则，禁止级规则**双向阻断开方与发药** |
| 医保目录对照 | 本院项目↔医保目录映射（甲乙丙类/自付比例/限价），模板下载 + 批量导入 |
| CSSD 消毒供应 | 回收→清洗→打包→灭菌→无菌→发放全状态机，BD 试验/生物监测双门槛 |
| PIVAS 静配 | 排药→配置→核对→配送→签收，**成品核对双人复核**（禁调配人自核） |
| ICU/PACU 评分 | 服务端汇总 APACHE II / SOFA / GCS / Aldrete / Steward + 转出标准 |
| 临床路径执行 | 入组/进度/变异四分类/出径，完成出径强制全部节点完成 |
| 手卫生监测 | 五时刻观察录入，依从率自动计算 |
| 病案借阅审批 | 申请→病案管理员批准/驳回→归还重置，审批工作台 |
| 病案 ICD 编码 | 文本诊断/手术→ICD 码绑定（字典校验、主诊断唯一），待编码工作台 + 统计 |
| 科室绩效核算 | 工作量×系数−成本分摊服务端核算，草稿→提交→审核发放 |
| 围术期抗菌药依从 | 切皮前 30-120 分钟给药依从率统计（按手术级别） |
| 急诊绿色通道计费 | 先救治后收费：关闭通道自动补记留观费用 |
| 日结缴费日口径 | 按 Payment.paid_time 收付实现制 + 渠道拆分 |
| 报损批次台账 | 报损审批按 FEFO 冲减批次并逐批写台账 |

### 规划中的模块

| 模块 | 功能说明 |
|:----:|:--------|
| 医保接口 | 医保实时结算、电子凭证 |
| PACS/RIS | 医学影像存储、阅片、报告 |
| 闭环医嘱 | 医嘱→摆药→执行→计费完整闭环 |
| CDSS 深度集成 | 审方规则引擎已上线（5 类规则）；规划接入专业知识库/肾功能剂量校正 |
| DRG/DIP 自动分组 | 手工分组与盈亏分析已上线；规划 CHS-DRG 分组器自动入组 |
| 互联网医院 | 在线问诊、复诊配药 |

> 完整 Roadmap 见 [doc/todos.md](doc/todos.md)，HIS 功能差距分析与交付记录见 [doc/his-feature-gap-analysis.md](doc/his-feature-gap-analysis.md)。

---

## 🏗 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                         前端层 (Browser)                       │
│        Vue 3 · Element Plus · Vuex · Vue Router · Rspack      │
├─────────────────────────────────────────────────────────────┤
│                         应用层 (FastAPI)                       │
│   75 个路由模块 · 541 个 API · JWT 认证 · 操作日志中间件         │
├─────────────────────────────────────────────────────────────┤
│                         数据层                                 │
│              SQLite (开发) / PostgreSQL (生产)                 │
│                   SQLAlchemy ORM · Alembic                    │
└─────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术 |
|:----:|:-----|
| 前端 | Vue 3.4+ / Element Plus 2.x / Vuex 4 / Vue Router 4 / Axios / Rspack |
| 后端 | FastAPI 0.111+ / SQLAlchemy 2.x / Pydantic 2.x / Alembic |
| 数据库 | SQLite（开发）/ PostgreSQL（生产推荐） |
| 容器化 | Docker / Docker Compose |
| 代码质量 | ruff (Python) / Prettier (JavaScript) |
| 测试 | pytest（后端 API 测试） |
| 安全 | bcrypt 密码加密、JWT 会话、操作日志审计 |

---

## 📁 项目结构

```
hoimsystem/
├── vue3-new-ui/                # Vue 3 前端
│   ├── src/
│   │   ├── views/              # 143 个页面组件，按模块分目录
│   │   │   ├── admin/          # 管理员模块
│   │   │   ├── patient/        # 患者服务
│   │   │   ├── doctor/         # 医生工作站
│   │   │   ├── pharmacy/       # 药房
│   │   │   ├── charge/         # 收费
│   │   │   ├── queue/          # 排队叫号
│   │   │   ├── checkin/        # 报到签到
│   │   │   ├── inpatient/      # 住院管理
│   │   │   ├── lab/            # 检验科
│   │   │   ├── exam/           # 体检中心
│   │   │   ├── followup/       # 随访
│   │   │   ├── report/         # 报表统计
│   │   │   └── system/         # 系统管理
│   │   ├── api/                # 接口封装
│   │   ├── router/             # 路由配置
│   │   ├── store/              # Vuex 状态管理
│   │   └── styles/             # 全局样式
│   ├── public/index.html
│   └── rspack.config.js
│
├── fastapi_be/                 # FastAPI 后端
│   ├── app/
│   │   ├── routers/            # 75 个路由模块
│   │   │   ├── user.py            # 登录认证
│   │   │   ├── admin.py           # 管理员（医生/病人/科室）
│   │   │   ├── patient.py         # 患者服务
│   │   │   ├── doctor.py          # 医生工作站
│   │   │   ├── pharmacy.py        # 药房
│   │   │   ├── purchase.py        # 药品采购
│   │   │   ├── consumable.py      # 耗材管理
│   │   │   ├── adverse_reaction.py # 药品ADR
│   │   │   ├── charge.py          # 收费
│   │   │   ├── queue.py           # 排队叫号
│   │   │   ├── triage.py          # 智能导诊
│   │   │   ├── triage_desk.py     # 分诊台
│   │   │   ├── checkin.py         # 报到签到
│   │   │   ├── vitalsign.py       # 生命体征
│   │   │   ├── lab.py             # 检验科
│   │   │   ├── exam.py            # 体检
│   │   │   ├── ward.py            # 病区床位
│   │   │   ├── admission.py       # 入院登记
│   │   │   ├── inpatient_order.py # 住院医嘱
│   │   │   ├── nursing.py         # 护士工作站
│   │   │   ├── inpatient_charge.py # 住院费用
│   │   │   ├── discharge.py       # 出院结算
│   │   │   ├── surgery.py         # 手术管理
│   │   │   ├── emr.py             # 电子病历
│   │   │   ├── clinical_pathway.py # 临床路径
│   │   │   ├── mdt.py             # 多学科会诊
│   │   │   ├── followup.py        # 随访
│   │   │   ├── referral.py        # 双向转诊
│   │   │   ├── digital_signature.py # CA签名
│   │   │   ├── adverse_event.py   # 不良事件
│   │   │   ├── report.py          # 报表统计
│   │   │   ├── system.py          # 操作日志/字典/配置
│   │   │   ├── backup.py          # 数据备份
│   │   │   └── upload.py          # 文件上传
│   │   ├── models.py           # 139 张表的 SQLAlchemy 模型
│   │   ├── schemas.py          # Pydantic 请求/响应模型
│   │   ├── dependencies.py     # JWT 解析、权限校验
│   │   ├── database.py         # 数据库连接
│   │   ├── config.py           # 配置加载
│   │   ├── pagination.py       # 分页工具
│   │   └── main.py             # 应用入口（CORS、中间件、路由注册）
│   ├── tests/                  # pytest 测试用例
│   └── requirements.txt
│
├── doc/                        # 项目文档
│   ├── README.md               # 文档索引
│   ├── architecture.md         # 架构与技术选型
│   ├── demandDoc.md            # 需求文档
│   ├── apiDoc.md               # API 接口文档
│   ├── databaseDoc.md          # 数据库文档
│   ├── deployDoc.md            # 部署文档
│   ├── user-manual.md          # 用户操作手册
│   └── todos.md                # 路线图与待办
│
├── doc_assets/                 # 文档资源（截图、流程图、SQL）
│
├── docker-compose.yml          # Docker Compose 编排
├── SECURITY.md                 # 安全策略
├── CONTRIBUTING.md             # 贡献指南
├── CHANGELOG.md                # 变更日志
├── LICENSE                     # MIT 许可证
└── README.md                   # 本文件
```

---

## 🚀 快速开始

### 环境要求

| 组件 | 版本 |
|:----:|:----:|
| Node.js | ≥ 16 |
| Python | ≥ 3.10 |
| 数据库 | 内置 SQLite，无需安装 |

### 1. 克隆项目

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem
```

### 2. 启动后端

```bash
cd fastapi_be

# 创建虚拟环境
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt

# 启动（首次启动自动建表）
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问 http://localhost:8000/docs 查看自动生成的 Swagger 文档。

### 3. 启动前端

```bash
cd vue3-new-ui

# 安装依赖
npm install --legacy-peer-deps

# 开发模式（端口 8091）
npm run serve:rspack

# 生产构建
npm run build
```

### 4. 访问系统

- 前端：http://localhost:8091
- 后端 API：http://localhost:8000/api
- 接口文档：http://localhost:8000/docs

### 5. Docker 一键启动（生产推荐）

```bash
docker-compose up -d
```

详细部署配置（Nginx、HTTPS、Systemd）见 [doc/deployDoc.md](doc/deployDoc.md)。

---

## 🔑 默认账号

系统初始化时自动创建以下测试账号（首次启动后端时建表，账号通过 API 或 SQL 注入）：

| 角色 | 用户名 | 密码 | 备注 |
|:----:|:------:|:----:|:----:|
| 管理员 | `admin` | `admin123` | 全部权限 |
| 超级管理员 | `super01` | `123456` | 全部权限（最高） |
| 科室主任 | `director01` | `123456` | 管理本科室业务 |
| 医生 | `doctor1` | `doctor123` | 普通医生 |
| 护士 | `nurse01` | `123456` | 护理工作 |
| 收费员 | `cashier01` | `123456` | 收费窗口 |
| 药师 | `pharmacist01` | `123456` | 药房工作 |
| 导诊员 | `guide01` | `123456` | 导诊台 |
| 检验技师 | `lab01` | `123456` | 检验科 |
| 挂号员 | `registrar01` | `123456` | 挂号服务 |
| 患者 | `patient1` | `123456` | 患者自助 |

> ⚠️ 生产环境部署前**必须**修改默认密码，并在 `.env` 中设置 `SECRET_KEY` 为随机强密钥（使用 `openssl rand -base64 32` 生成）。

---

## 👥 系统角色

系统支持 8 种角色，覆盖门诊全岗位：

| 角色 | 主要权限 |
|:----:|:--------|
| **管理员** (admin) | 全局管理：用户、医生、病人、科室、药品、通知、收费、系统配置 |
| **科室主任** (director) | 科室管理：本科室排班、医生管理、发布通知、处方点评 |
| **医生** (doctor) | 诊疗工作：病历书写、处方开立、检查申请、排班查看 |
| **护士** (nurse) | 护理工作：预检分诊、生命体征录入、住院护理、随访 |
| **收费员** (cashier) | 收费窗口：现场挂号/退号、费用结算、日结对账 |
| **药师** (pharmacist) | 药房管理：处方审核、发药确认、退药处理、库存管理 |
| **导诊员** (guide) | 导诊服务：分诊台管理、智能导诊、候诊队列 |
| **患者** (patient) | 自助服务：挂号/预约、缴费、查报告、健康档案、评价 |

---

## 📚 文档索引

| 文档 | 说明 |
|:----:|:-----|
| [文档总览](doc/README.md) | 所有文档的导航索引 |
| [架构文档](doc/architecture.md) | 系统架构、技术选型、设计原则 |
| [需求文档](doc/demandDoc.md) | 功能需求、业务流程、非功能需求 |
| [API 文档](doc/apiDoc.md) | 核心接口定义（全量 541 见 RBAC 矩阵） |
| [数据库文档](doc/databaseDoc.md) | 139 张表结构定义及 ER 关系 |
| [部署文档](doc/deployDoc.md) | 开发/生产/Docker 部署指南 |
| [用户手册](doc/user-manual.md) | 按角色分组的用户操作指南 |
| [路线图](doc/todos.md) | 已完成功能与待开发模块 |
| [安全策略](SECURITY.md) | 安全漏洞上报与处理流程 |
| [贡献指南](CONTRIBUTING.md) | 代码规范、提交流程 |
| [变更日志](CHANGELOG.md) | 历史版本变更记录 |

---

## ✨ 项目亮点

- **业务覆盖广**：门诊 + 住院 + 药房 + 检验 + 体检 + 手术，9 大领域 40+ 模块
- **代码质量高**：247 个 API 按模块清晰组织，前后端分离，组件复用
- **开发体验好**：FastAPI 自动文档、热重载、SQLite 零配置启动
- **可观测性强**：操作日志中间件自动记录、操作时间精确到秒
- **安全可控**：JWT 认证、bcrypt 密码、身份证号脱敏显示、操作审计
- **UI 体验佳**：Element Plus 组件库、全局样式工具类、空状态/加载状态全覆盖

---

<a id="performance-benchmark"></a>

## ⚡ 性能测试

### 当前状态

> **基线待重测（2026-09-03）**：此前发布的吞吐、延迟、失败率和并发建议来自旧基准。旧服务器通过 `StaticPool` 共享单个 SQLite 连接；旧混合场景又用预生成的 `admin` token 执行仅允许患者或医生执行的写操作，并且只按 HTTP 状态统计，会把响应体 `code != 200` 的业务失败计为成功。旧数据与当前实现不可比，不作为当前性能基线、容量建议或 SLA 依据。旧结果中的 HTTP 401 表示认证失败，不是“连接池耗尽”。

### 修复后的基准配置

| 项目 | 配置 |
|:----:|:-----|
| 服务器 | FastAPI + Uvicorn，1 worker |
| 数据库 | 专用 SQLite 文件 `fastapi_be/benchmark.db` |
| 数据初始化 | 仅重建专用基准库并写入基准账号与业务数据；不继承外部 `DATABASE_URL` |
| 连接方式 | SQLAlchemy `QueuePool`；重叠 Session 使用独立 DBAPI 连接 |
| 认证 | 开测前调用 `/api/login` 获取 token，并校验 `sub` / `iat` / `exp`；失败时终止测试 |
| 角色 | 查询使用管理员；预约使用患者；处方使用医生 |
| 写入目标 | 开测时读取实际排班、患者和可用药品，构造字段一致且不重复的预约请求 |
| 混合场景 | 按任务权重约 96.2% 查询、3.8% 写入；8 个查询和 2 个写入场景 |
| 成功判定 | 预约和处方同时要求 HTTP 2xx 与响应体 `code == 200` |
| 工具 | Locust 2.44.4，单进程 headless 模式 |
| 时长 | 每轮 30 秒，无显式预热 |

`locust_readonly_pool.py` 不修改业务数据，但并非全部使用 GET：它还使用 `POST /api/log/getList` 执行查询。当前 SQLite 基准允许多个数据库连接，但 SQLite 的文件级写竞争仍然存在。PostgreSQL 尚未在同一提交、硬件、数据规模和负载模型下实测，不应从 SQLite 结果外推具体吞吐、延迟或并发上限。

### 测试方法复现

`init_benchmark_data.py` 会清空并重建仓库内的 `fastapi_be/benchmark.db`，不会使用环境中的其他数据库。每轮测试前都应重新初始化。

```bash
# 终端 1：初始化并启动基准服务
cd fastapi_benchmark
export SECRET_KEY="benchmark-only-local-secret-at-least-32-bytes"
python init_benchmark_data.py
uvicorn run_benchmark:app --host 0.0.0.0 --port 8000

# 终端 2：选择一个场景运行（如配置了 HTTP 代理，请将 localhost 加入 NO_PROXY）
cd fastapi_benchmark
mkdir -p benchmark_results
locust -f locust_final.py --headless -u 50 -r 25 -t 30s \
    --host http://localhost:8000 --csv=benchmark_results/mixed_50u \
    --exit-code-on-error 1

# 如需改测只读场景：先停止终端 1，重新初始化并启动服务，再执行下列命令
locust -f locust_readonly_pool.py --headless -u 50 -r 25 -t 30s \
    --host http://localhost:8000 --csv=benchmark_results/readonly_50u \
    --exit-code-on-error 1
```

初始化脚本会创建与 Locust 默认配置一致的管理员、医生和患者基准身份。Locust 会在每轮开始时实时登录，不使用固定的 `tokens.json`。修复后的实测结果将在重新执行完整基准后补充。

---

## 🔧 开发约定

- 提交信息：`<type>: <description>`（type 取自 conventional commits：feat/fix/docs/style/refactor/test/chore）
- 分支策略：`master` 为主分支，特性开发新建分支
- 代码风格：后端遵循 ruff 默认规则，前端遵循 Prettier 默认规则
- 接口路径：所有 API 以 `/api/` 为前缀
- 数据库表名：统一前缀 `hoimsystem_`

---

## 📷 截图预览

![病人就医流程](doc_assets/PatientAccessFlow.png)

更多截图见 [doc_assets/](doc_assets/) 目录。

---

## 📄 许可证

[MIT](LICENSE)

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

**联系方式**：palpitate.xus@outlook.com
