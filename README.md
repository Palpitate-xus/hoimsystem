# HOIM 医院信息管理系统

[English](README.en.md) | **中文**

基于 **Vue 3 + FastAPI** 的中小型医院综合信息管理系统，覆盖 **门诊、住院、药房、检验、体检、收费** 等核心业务全流程。

AI 平台提供 [80 项能力](doc/ai-capabilities.md)，包括 63 项文本 LLM 任务，以及语音、影像、心电、风险评估、预测优化和本地固定统计。医护人员可从业务页面或 AI 工作台发起任务，超级管理员统一管理模型、Prompt、知识、来源、权限和用量。工作台按业务分类展示任务，常用收藏按账号和角色保存在本机；个人中心展示账号与使用偏好。配置与使用方法见 [AI 使用指南](doc/ai-guide.md)。

管理员可按岗位和用户配置接口操作、AI 能力、患者列表字段及临床数据范围，前端导航与后端校验使用同一份有效权限。操作步骤见 [权限管理指南](doc/permission-management.md)。

[![Version](https://img.shields.io/badge/version-2.1.0-blue)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Vue](https://img.shields.io/badge/Vue-3.x-4FC08D)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.162.0-009688)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)

---

## 项目规模

| 维度 | 数量 |
|:----:|:----:|
| 后端路由模块 | **135** 个已挂载模块 |
| API 接口 | **1,092** 个 RBAC 路由方法（见 [访问矩阵](doc/api-rbac-matrix.md)） |
| 数据库表定义 | **269** 个 ORM 表定义（含 AI 来源与治理表） |
| 前端页面 | **161** 个 Vue 页面文件 |
| 用户角色 | **11** 种（含超级管理员、检验技师和挂号员） |
| AI 能力目录 | **80** 项，其中 **63** 项使用文本 LLM |

统计依据：路由按 RBAC 清单核对，表按 ORM 定义、页面按 `vue3-new-ui/src/views/**/*.vue` 统计。

---

## 功能特性

### 核心业务（9 大领域 / 40+ 模块）

#### 门诊管理
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

#### 医生工作站
| 模块 | 功能说明 |
|:----:|:--------|
| 排班管理 | 医生周排班、号源数量、专家标记 |
| 电子病历 | 主诉/现病史/既往史/诊断/治疗，模板复用 |
| 处方开立 | 药品搜索、剂量频次途径、库存校验，结合结构化临床档案执行 CDSS 规则 |
| 检查检验申请 | 检查类型、项目、紧急标记 |
| 考勤签到 | 每日签到/签退、出勤统计 |
| 多学科会诊 | MDT 申请、参与科室、结果录入 |
| 临床路径 | 路径模板管理、进度跟踪 |

#### 药房药库
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

#### 住院管理
| 模块 | 功能说明 |
|:----:|:--------|
| 病区床位 | 病区维护、床位状态、空床查询 |
| 入院登记 | 4 种入院类型、床位分配、押金登记 |
| 住院医嘱 | 长期/临时医嘱、审核、停止、撤销 |
| 护士工作站 | 医嘱执行、护理记录、体温录入，eMAR 条码双核验后给药 |
| 住院费用 | 费用明细、每日清单、押金扣减 |
| 出院结算 | 总费用计算、押金退还 |

#### 电子病历（EMR）
| 模块 | 功能说明 |
|:----:|:--------|
| 病历模板 | 病种模板、复用 |
| 结构化病历 | 主诉/现病史/既往史/查体/诊断/治疗 |
| 病程记录 | 日常病程、上级查房 |
| 查房记录 | 主任/副主任查房、查房意见 |
| 病历质控 | 三级签名、归档 |
| CA 数字签名 | 电子签名、签名验证 |

#### 检验科 / 体检
| 模块 | 功能说明 |
|:----:|:--------|
| 检查检验 | 申请、样本接收、结果录入、审核 |
| 检验结果查询 | 结果列表、异常标记、报告查看 |
| 体检套餐 | 套餐定义、项目组合 |
| 体检预约 | 在线预约、状态跟踪 |
| 体检记录 | 检查录入、结果汇总 |
| 体检报告 | 报告生成、综合评估 |

#### 手术管理
| 模块 | 功能说明 |
|:----:|:--------|
| 手术申请 | 急诊/择期、麻醉方式 |
| 手术排台 | 主刀/麻醉医师分配、时间安排 |
| 麻醉记录 | 麻醉过程、用药记录 |

#### 患者服务
| 模块 | 功能说明 |
|:----:|:--------|
| 健康档案 | 个人信息、过敏史、就诊记录 |
| 病历查询 | 历次就诊病历查看 |
| 处方查询 | 处方明细、状态 |
| 预交金管理 | 充值、查询、扣费、退款 |
| 双向转诊 | 门诊/住院/急诊转诊 |
| 复诊随访 | 随访计划、患者反馈、随访记录 |
| 满意度评价 | 就诊评价、评分统计 |

#### 系统平台
| 模块 | 功能说明 |
|:----:|:--------|
| 用户权限 | 岗位与个人接口权限、AI 使用权限、患者列表字段、数据范围、账号停用、角色调整、密码重置与变更审计 |
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
| CDSS 临床上下文 | 结构化维护过敏、诊断、肝肾功能、妊娠/哺乳信息；处方规则显示命中依据与数据来源 |
| DRG/DIP 自动分组 | 版本化规则维护，按主要诊断/手术和费用区间自动匹配并保留规则版本 |
| 对外集成发件箱 | 业务提交与 LIS/PACS/医保/支付事件同事务落库，独立调度器重试、死信和人工重放 |
| 运营分析 | 每日预聚合门诊、住院、收入、处方及床位指标，支持管理员手工刷新 |

### 专业业务与管理
| 模块 | 功能说明 |
|:----:|:--------|
| 审方规则引擎 | 药师维护配伍、禁忌、剂量、重复、过敏及患者条件 6 类规则，禁止级规则**双向阻断开方与发药** |
| 医保目录对照 | 本院项目↔医保目录映射（甲乙丙类/自付比例/限价），模板下载 + 批量导入 |
| CSSD 消毒供应 | 回收→清洗→打包→灭菌→无菌→发放全状态机，BD 试验/生物监测双门槛 |
| PIVAS 静配 | 排药→配置→核对→配送→签收，**成品核对双人复核**（禁调配人自核） |
| ICU/PACU 评分 | 服务端汇总 APACHE II / SOFA / GCS / Aldrete / Steward + 转出标准 |
| 临床路径执行 | 入组/进度/变异四分类/出径，完成出径强制全部节点完成 |
| 手卫生监测 | 五时刻观察录入，依从率自动计算 |
| 病案借阅审批 | 申请→病案管理员批准/驳回→归还重置，审批工作台 |
| 病案 ICD 编码 | 文本诊断/手术→ICD 码绑定（字典校验、主诊断唯一），待编码工作台 + 统计 |
| 科室绩效核算 | （工作量−成本分摊）×系数由服务端核算，草稿→提交→审核发放 |
| 围术期抗菌药依从 | 切皮前 30-120 分钟给药依从率统计（按手术级别） |
| 急诊绿色通道计费 | 先救治后收费：关闭通道自动补记留观费用 |
| 日结缴费日口径 | 按 Payment.paid_time 收付实现制 + 渠道拆分 |
| 报损批次台账 | 报损审批按 FEFO 冲减批次并逐批写台账 |

### 临床知识、影像与外部对接

| 模块 | 功能说明 |
|:----:|:--------|
| 医保与集成 | 医保目录映射和批量导入、结算请求与回执、版本化 DRG/DIP 自动分组；集成发件箱支持重试、死信处理与人工重放 |
| 临床知识与 CDSS | 结构化患者上下文、审方与剂量规则、审核知识检索、院内临床路径知识导入；展示规则依据和数据来源 |
| 影像服务 | 检查申请、报告提交与审核、PACS 回传、外部阅片，以及私有单帧 DICOM 原图登记和像素预览 |
| 患者与复诊服务 | 预约挂号、本人就诊记录和处方查询、医生随访计划、复诊预约与随访反馈 |

对接配置见 [集成指南](doc/integration-guide.md)，各角色的操作步骤见 [用户手册](doc/user-manual.md)。

---

## AI 平台

业务工作台为 `/#/ai/workbench`，超级管理员管理中心为 `/#/ai/manage`。门诊病历、处方、住院、药房、检验及运营等业务页面也提供绑定当前记录的入口。

| 功能范围 | 功能说明 |
| --- | --- |
| 临床辅助与文书 | 患者摘要、鉴别诊断与治疗路径候选、处方核查、病历与报告草稿；按任务核对患者关系、就诊、原记录和适用审核知识 |
| 语音、心电与影像 | 私有录音及听音复核、WFDB 原文件与波形、单帧 DICOM 原图及专用适配器；可选本地研究服务的准备与核对流程见使用指南 |
| 风险与固定计算 | NEWS2、成人 AKI、qSOFA、SOFA-1 六轴日评估与变化核对，以及受审排班、床位、物资和库存工作流；固定计算与模型解释分别处理 |
| 来源与专用任务 | 完整账目、评价、指南及双版本原文、药品说明书、科研队列与变量、去标识候选、事件 RCA、有限病例统计、运维材料及合成教学 |
| 文书与教学复核 | 文书正文与摘要、警示、缺项分开，选择栏目并确认复核后复制；教学练习与 AI 讲解分别提交，固定成绩与模型反馈分开 |

超级管理员管理中心提供 41 个入口，支持跨组搜索，按四组组织：

| 管理分组 | 主要内容 |
| --- | --- |
| 功能与模型 | 启停、使用角色、模型服务、有限重试与超时、限额、验证状态及各功能的 Prompt 版本 |
| 知识与数据 | 知识审核、来源登记、专业复核和独立发布 |
| 任务与用量 | 任务追踪、结果与反馈、调用用量及统计 |
| 权限与审计 | 患者访问授权、配置审计及管理操作追查 |

**Prompt 管理**：79 项能力支持独立任务 Prompt、不可变版本、历史版本切换和任务快照；本地固定统计采用受审配方。临床文书、药学、运营和教学任务分别定义内容和表达要求，文书正文、依据、缺项与复核事项分区呈现。

**配置与使用**：

1. 以 `super_admin` 登录管理中心，配置模型服务、凭据与功能限额。
2. 为功能配置使用角色、任务 Prompt、知识和来源；来源内容按用途授权访问。
3. 按功能要求完成专业复核、服务核对及验证登记，再启用功能。
4. 使用者从工作台或业务页面提交任务，核对来源、结果与复核事项；文书选择栏目并确认复核后复制，诊疗决策由医护人员确认。

各功能的输入、输出和默认角色见 [能力清单](doc/ai-capabilities.md)，配置步骤见 [使用指南](doc/ai-guide.md)。功能、AI、事务并发及性能的执行结果见 [系统验证](doc/validation/2026-10-27/README.md)，复现步骤见 [测试指南](doc/testing.md)。

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                         前端层 (Browser)                       │
│        Vue 3 · Element Plus · Vuex · Vue Router · Rspack      │
├─────────────────────────────────────────────────────────────┤
│                         应用层 (FastAPI)                       │
│       FastAPI · AI Worker · JWT/RBAC · 指标/审计                │
├─────────────────────────────────────────────────────────────┤
│                         数据层                                 │
│              SQLite (开发) / PostgreSQL (生产)                 │
│                   SQLAlchemy ORM · Alembic                    │
└─────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层级 | 技术 |
|:----:|:-----|
| 前端 | Vue 3.5+ / Element Plus 2.x / Vuex 4 / Vue Router 5 / Axios / Rspack 2 |
| 后端 | FastAPI 0.111+ / SQLAlchemy 2.x / Pydantic 2.x / Alembic |
| 数据库 | SQLite（仅开发）/ PostgreSQL（生产强制） |
| 容器化 | Docker / Docker Compose |
| 代码质量 | ruff (Python) / Prettier (JavaScript) |
| 测试 | pytest（后端 API 测试） |
| 安全 | bcrypt 密码加密、JWT 会话、操作日志审计 |

---

## 项目结构

```
hoimsystem/
├── vue3-new-ui/                # Vue 3 前端
│   ├── src/
│   │   ├── views/              # 页面组件，按业务模块分目录
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
│   │   ├── routers/            # 业务及 AI 路由模块
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
│   │   ├── ai/                 # AI 目录、Prompt、来源、任务及 worker
│   │   ├── models.py           # ORM 模型入口，注册业务及 AI 模型
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

## 快速开始

### 本地演示

安装 Docker Compose 和下表中的 Python、Node.js 环境后，从仓库根目录执行：

```bash
npm --prefix vue3-new-ui ci --legacy-peer-deps
python scripts/local_preview.py start
```

页面地址为 **http://localhost:51891**，API 文档为 **http://localhost:51800/docs**。两者默认监听 `0.0.0.0`，局域网访问时将 localhost 换为开发机 IP。使用 `super01 / 123456` 查看超级管理员管理中心，使用 `doctor1 / doctor123` 查看医生工作站。

演示自动创建独立数据库、账号和合成病历，配置患者摘要、门诊病历草稿及运营问答的模拟模型服务。临床任务使用超级管理员预览，保留原有审核与启用要求。查看状态、停止服务和远程端口转发见 [本地演示指南](doc/local-preview.md)。

以下步骤用于分别运行前后端开发服务。

### 环境要求

| 组件 | 版本 |
|:----:|:----:|
| Node.js | 24.x（容器固定 24.22.1） |
| npm | ≥ 10.0.0 |
| Python | 3.12.x（容器固定 3.12.16） |
| 数据库 | 内置 SQLite，无需安装 |

### 1. 克隆项目

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem
```

### 2. 启动后端

API 和 AI worker 使用相同的数据库、`SECRET_KEY` 及 AI 配置。

```bash
cd fastapi_be

# 创建虚拟环境
python -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# 安装依赖
python -m pip install --require-hashes -r requirements-build.lock
python -m pip install --only-binary=:all: --require-hashes -r requirements.lock

# 从示例创建配置文件，并设置 .env 中的数据库与 SECRET_KEY
cp -n .env.example .env

# 初始化空库或升级已纳入 Alembic 管理的数据库
python -m app.db_migrate

# 启动 API
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问 http://localhost:8000/docs 查看自动生成的 Swagger 文档。当前迁移头为 `20261029_session_binding`；从旧版本升级后重新登录一次，登录令牌绑定用户编号与账号唯一标识。

需要处理 AI 排队任务时，从仓库根目录另开终端，使用相同虚拟环境和数据库配置运行：

```bash
cd fastapi_be
source venv/bin/activate
python -m app.ai.worker
```

已有数据库的备份、结构核对、迁移与接管步骤见 [部署手册](doc/installation-guide.md#34-数据库初始化)。AI 模型与功能的配置顺序见 [AI 使用指南](doc/ai-guide.md)。

### 3. 启动前端

从仓库根目录另开终端：

```bash
cd vue3-new-ui

# 安装依赖
npm ci --legacy-peer-deps

# 开发模式（端口 8091）
npm run serve:rspack

# 生产构建
npm run build

# 依赖审计、生产构建和资源体积检查
npm run verify
```

### 4. 访问系统

- 前端：http://localhost:8091
- 后端 API：http://localhost:8000/api
- 接口文档：http://localhost:8000/docs

### 5. Docker 一键启动（生产推荐）

在仓库根目录执行：

```bash
export POSTGRES_PASSWORD='请替换为数据库强密码'
export SECRET_KEY="$(openssl rand -base64 48)"
export ALLOWED_ORIGINS='https://his.example.com'
docker compose up -d
```

详细部署配置（Nginx、HTTPS、Systemd）见 [doc/deployDoc.md](doc/deployDoc.md)。

---

## 本地演示账号

新建的本地开发库完成迁移后，可在 `fastapi_be/` 目录中运行 [演示账号脚本](fastapi_be/seed_default_accounts.py)，创建以下账号及必要的医生、患者档案：

```bash
python seed_default_accounts.py
```

| 角色 | 用户名 | 密码 | 备注 |
|:----:|:------:|:----:|:----:|
| 管理员 | `admin` | `admin123` | 常规业务管理 |
| 超级管理员 | `super01` | `123456` | 含 AI 平台管理，来源正文另核用途许可 |
| 科室主任 | `director01` | `123456` | 管理本科室业务 |
| 医生 | `doctor1` | `doctor123` | 普通医生 |
| 护士 | `nurse01` | `123456` | 护理工作 |
| 收费员 | `cashier01` | `123456` | 收费窗口 |
| 药师 | `pharmacist01` | `123456` | 药房工作 |
| 导诊员 | `guide01` | `123456` | 导诊台 |
| 检验技师 | `lab01` | `123456` | 检验科 |
| 挂号员 | `registrar01` | `123456` | 挂号服务 |
| 患者 | `patient1` | `123456` | 患者自助 |

生产环境使用交互式强口令初始化首个超级管理员，操作步骤见 [部署手册](doc/installation-guide.md#34-数据库初始化)。

---

## 系统角色

系统支持 11 种角色。岗位提供默认业务资格，管理员配置角色策略与用户策略后形成实际可用权限：

| 角色 | 主要权限 |
|:----:|:--------|
| **管理员** (admin) | 常规业务管理：用户、医生、病人、科室、药品、通知、收费、系统配置，以及普通岗位和用户的权限配置 |
| **超级管理员** (super_admin) | 管理管理员权限、AI 配置、Prompt、知识、来源治理和审计；来源正文按用途授权访问 |
| **科室主任** (director) | 科室管理：本科室排班、医生管理、发布通知、处方点评 |
| **医生** (doctor) | 诊疗工作：病历书写、处方开立、检查申请、排班查看 |
| **护士** (nurse) | 护理工作：预检分诊、生命体征录入、住院护理、随访 |
| **收费员** (cashier) | 收费窗口：现场挂号/退号、费用结算、日结对账 |
| **药师** (pharmacist) | 药房管理：处方审核、发药确认、退药处理、库存管理 |
| **导诊员** (guide) | 导诊服务：分诊台管理、智能导诊、候诊队列 |
| **检验技师** (lab_technician) | 样本接收、结果录入/审核、危急值闭环、质控 |
| **挂号员** (registrar) | 窗口预约确认、取消和患者建卡服务 |
| **患者** (patient) | 自助服务：挂号/预约、缴费、查报告、健康档案、评价 |

---

## 文档索引

| 文档 | 说明 |
|:----:|:-----|
| [文档总览](doc/README.md) | 所有文档的导航索引 |
| [架构文档](doc/architecture.md) | 系统架构、技术选型、设计原则 |
| [前端开发](vue3-new-ui/README.md) | 前端启动、API 配置、业务入口与构建检查 |
| [需求文档](doc/demandDoc.md) | 功能需求、业务流程、非功能需求 |
| [API 文档](doc/apiDoc.md) | 核心接口定义；当前 1,092 个 RBAC 路由方法见 [访问矩阵](doc/api-rbac-matrix.md) |
| [数据库文档](doc/databaseDoc.md) | 核心表结构说明；当前 269 个 ORM 表定义以模型源码为准 |
| [权限管理](doc/permission-management.md) | 岗位与用户策略、接口与字段权限、数据范围、停用、审计和会话升级 |
| [AI 使用指南](doc/ai-guide.md) | 工作台、超管配置、来源准备与功能启用 |
| [AI 能力清单](doc/ai-capabilities.md) | 全部 80 项功能、输入、产出及默认角色 |
| [默认 Prompt](doc/ai-prompts.json) | 任务文本、目录版本及固定系统契约 |
| [AI 体验验证](doc/ai-experience-verification.json) | Prompt、文书、管理导航与业务界面的测试记录 |
| [部署文档](doc/deployDoc.md) | 开发/生产/Docker 部署指南 |
| [用户手册](doc/user-manual.md) | 按角色分组的用户操作指南 |
| [路线图](doc/todos.md) | 功能清单与项目规划 |
| [安全策略](SECURITY.md) | 安全漏洞上报与处理流程 |
| [贡献指南](CONTRIBUTING.md) | 代码规范、提交流程 |
| [变更日志](CHANGELOG.md) | 历史版本变更记录 |

---

## 运行与维护

- 静态 RBAC 漂移检查、lint、业务测试、依赖审计和 bundle 预算检查，命令见 [测试指南](doc/testing.md)。
- 存活与就绪探针、Prometheus 指标、请求 ID 和操作审计，用于定位请求失败、依赖故障与配置变更。
- API、AI worker 和调度器独立运行；业务集成支持有限重试、死信查询与人工重放。
- PostgreSQL 迁移、数据备份、恢复与进程管理见 [部署手册](doc/installation-guide.md)。

---

<a id="performance-benchmark"></a>

## 性能测试

### 可复现的 PostgreSQL 基准

基准环境使用独立的 PostgreSQL 容器、4 个 Gunicorn worker 和临时数据卷，不复用开发或生产数据库。破坏性初始化只接受名为 `hoimsystem_benchmark` 的目标，并要求 `BENCHMARK_RESET_CONFIRM` 与数据库名一致。数据配置包括 `smoke`、`small`、`medium`、`large`，最大可生成 10 万患者和 50 万条历史记录。

从仓库根目录执行：

```bash
cd fastapi_benchmark

# small 为默认配置；也可改为 smoke / medium / large
BENCHMARK_PROFILE=small docker compose up --build -d

# 混合读写场景。token 在开测时登录生成，写请求使用合法的患者/医生身份
locust -f locust_final.py --headless -u 50 -r 10 -t 5m \
  --host http://localhost:18000 --csv=benchmark_results/mixed_50u \
  --exit-code-on-error 1

# 结束后删除临时数据库容器
docker compose down -v
```

所有 Locust 请求同时检查 HTTP 状态和响应体 `code == 200`；运行元数据记录代码版本、数据配置、并发参数和脱敏后的数据库目标。使用目标硬件和数据配置运行基准，可记录 P95/P99、错误率、连接池等待和 PostgreSQL 慢查询，用于容量规划；操作方法见 [性能指南](doc/performance.md)。

---

## 开发约定

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

依赖锁定、审计与镜像维护见 [依赖维护](doc/dependencies.md)；版本校验与本地发布步骤见 [发布流程](doc/release-process.md)。
