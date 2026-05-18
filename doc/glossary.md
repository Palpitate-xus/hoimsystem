# 术语表（Glossary）

> 项目中使用的医疗术语和技术术语的统一定义，避免歧义。
> 添加新术语请按字母顺序插入。

---

## 一、医疗业务术语

### A

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **ADR** | Adverse Drug Reaction | 药品不良反应 | 患者使用药品后出现的非预期有害反应 |

### B

| 术语 | 含义 |
|:----:|:----|
| **病案首页** | 完整的住院病历摘要，包含 ICD 诊断编码、手术编码、医保信息等，是医保结算和病案统计的基础 |
| **病程记录** | 患者住院期间病情发展和治疗过程的记录，分日常病程、上级查房记录 |
| **闭环管理** | 医嘱从开立、审核、执行到反馈形成闭环，确保医疗安全 |

### C

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **CA** | Certificate Authority | 数字证书 | 电子签名用的证书，用于医生签名病历/处方 |
| **CDR** | Clinical Data Repository | 临床数据中心 | 整合多系统的患者临床数据，提供 360° 患者视图 |
| **CDSS** | Clinical Decision Support System | 临床决策支持系统 | 提供用药安全、过敏提醒、合理用药建议 |
| **CIS** | Clinical Information System | 临床信息系统 | 住院医嘱、护理、病程等临床业务的总称 |

### D

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **DICOM** | Digital Imaging and Communications in Medicine | 医学数字影像通信 | 医学影像的标准格式 |
| **DIP** | Diagnosis-Intervention Packet | 病种分值付费 | 中国特色的医保付费方式 |
| **DRG** | Diagnosis Related Groups | 疾病诊断相关分组 | 按病种打包付费，全球通用 |

### E

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **EMR** | Electronic Medical Record | 电子病历 | 包含主诉、现病史、既往史、查体、诊断、治疗 |

### F

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **FHIR** | Fast Healthcare Interoperability Resources | 快速医疗互操作资源 | HL7 推出的新一代医疗数据交换标准 |

### G

| 术语 | 含义 |
|:----:|:----|
| **挂号** | 患者预约就诊号源的过程，可以是预约/现场/窗口 |
| **挂号号源** | 医生每个时段开放的可预约名额，由排班决定 |

### H

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **HIS** | Hospital Information System | 医院信息系统 | 医院信息化的核心系统 |
| **HL7** | Health Level Seven | 医疗信息交换协议 | 医疗信息系统之间的数据交换标准 |
| **HRP** | Hospital Resource Planning | 医院资源规划 | 类似 ERP，含人事/资产/物资/财务 |

### I

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **ICD-10** | International Classification of Diseases | 国际疾病分类 | 标准化疾病诊断编码 |
| **ICD-9-CM-3** | - | 国际手术操作编码 | 标准化手术编码 |
| **ICU** | Intensive Care Unit | 重症监护室 | 重症患者集中救治区域 |

### L

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **LIS** | Laboratory Information System | 实验室信息系统 | 检验科业务系统 |

### M

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **MDT** | Multi-Disciplinary Treatment | 多学科联合诊疗 | 多个科室联合会诊一个复杂病例 |

### N

| 术语 | 含义 |
|:----:|:----|
| **NIS** | Nursing Information System / 护理信息系统 | 护理记录、医嘱执行 |

### O

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **OPD** | Out-Patient Department | 门诊部 | 不需要住院的医疗服务 |
| **OR** | Operating Room | 手术室 | - |

### P

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **PACS** | Picture Archiving and Communication System | 影像归档和通信系统 | 医学影像的存储、调阅、传输 |
| **PDA** | Personal Digital Assistant | 移动护理终端 | 护士床旁使用，扫腕带做核对 |
| **PIVAS** | Pharmacy Intravenous Admixture Service | 静脉用药调配中心 | 集中配置静脉输液 |

### R

| 缩写 | 全称 | 中文 | 含义 |
|:----:|:----|:----|:----|
| **RIS** | Radiology Information System | 放射科信息系统 | 放射检查申请、报告、影像归档 |

### S

| 术语 | 含义 |
|:----:|:----|
| **SPD** | Supply Processing and Distribution | 医用物资供应链 |
| **三级查房** | 主任医师/副主任医师/主治医师/住院医师的查房制度 |

### W

| 术语 | 含义 |
|:----:|:----|
| **危急值** | 检验结果出现严重异常，需要立即报告临床医生的值 |
| **腕带** | 患者入院时佩戴的身份识别带，扫码用于身份核对 |
| **违约** | 患者预约后未按时就诊，达到一定次数会暂停预约资格 |

---

## 二、本项目业务术语

### 角色

| 角色 | 英文 | 说明 |
|:----:|:----|:----|
| 管理员 | admin | 全局管理：用户、医生、病人、科室、药品、通知 |
| 科室主任 | director | 本科室管理：排班、医生、处方点评 |
| 医生 | doctor | 诊疗：病历、处方、检查申请、考勤 |
| 护士 | nurse | 护理：分诊、生命体征、住院护理 |
| 收费员 | cashier | 收费：窗口挂号/退号、费用结算 |
| 药师 | pharmacist | 药房：处方审核、发药、库存 |
| 导诊员 | guide | 导诊：分诊台、智能导诊、候诊队列 |
| 患者 | patient | 自助：挂号/预约、缴费、查报告 |

### 业务状态码

#### 预约状态
| 值 | 含义 |
|:--:|:----|
| 0 | 未就诊（已预约） |
| 1 | 已就诊 |
| 2 | 已取消 |
| 3 | 已违约 |

#### 处方状态
| 值 | 含义 |
|:--:|:----|
| 0 | 待审核 |
| 1 | 已审核 |
| 2 | 已发药 |
| 3 | 已取消 |
| 4 | 已退药 |

#### 入院状态
| 值 | 含义 |
|:--:|:----|
| 0 | 待入院 |
| 1 | 在院 |
| 2 | 已出院 |
| 3 | 已退院 |

#### 医嘱状态
| 值 | 含义 |
|:--:|:----|
| 0 | 新开 |
| 1 | 已审核 |
| 2 | 执行中 |
| 3 | 已停止 |
| 4 | 已撤销 |

完整状态码参见 [databaseDoc.md](databaseDoc.md)。

### 业务流程关键节点

| 流程 | 关键节点 |
|:----:|:--------|
| 门诊就诊 | 挂号 → 报到 → 候诊 → 接诊 → 病历 → 处方 → 缴费 → 取药/检查 → 离院 |
| 住院诊疗 | 入院登记 → 床位分配 → 医嘱开立 → 医嘱执行 → 病程记录 → 出院结算 |
| 手术 | 手术申请 → 排台 → 麻醉记录 → 手术记录 → 术后随访 |
| 体检 | 套餐选择 → 预约 → 报到 → 项目检查 → 总检 → 报告生成 |

---

## 三、技术术语

### 架构

| 术语 | 含义 |
|:----:|:----|
| **SPA** | Single Page Application 单页应用 |
| **SSR** | Server-Side Rendering 服务端渲染 |
| **CSR** | Client-Side Rendering 客户端渲染 |
| **REST** | Representational State Transfer 表征状态转移，HTTP API 风格 |
| **ORM** | Object-Relational Mapping 对象关系映射（如 SQLAlchemy） |
| **ASGI** | Asynchronous Server Gateway Interface 异步服务网关接口 |
| **WSGI** | Web Server Gateway Interface（同步） |

### 安全

| 术语 | 含义 |
|:----:|:----|
| **JWT** | JSON Web Token，用于用户会话 |
| **CORS** | Cross-Origin Resource Sharing 跨域资源共享 |
| **XSS** | Cross-Site Scripting 跨站脚本攻击 |
| **CSRF** | Cross-Site Request Forgery 跨站请求伪造 |
| **SQL 注入** | SQL Injection 通过用户输入注入恶意 SQL |
| **bcrypt** | 密码哈希算法，安全存储密码 |

### 前端

| 术语 | 含义 |
|:----:|:----|
| **HMR** | Hot Module Replacement 热模块替换，开发时不刷新更新 |
| **SFC** | Single File Component Vue 单文件组件 (.vue) |
| **Composition API** | Vue 3 引入的组合式 API（setup script） |
| **Options API** | Vue 2 风格的选项式 API（data/methods/computed） |
| **Vuex** | Vue 的状态管理库 |
| **Pinia** | 新一代 Vue 状态管理（本项目用 Vuex） |
| **Rspack** | 基于 Rust 的高性能打包工具 |

### 后端

| 术语 | 含义 |
|:----:|:----|
| **FastAPI** | Python 现代 Web 框架 |
| **Pydantic** | 数据校验库，FastAPI 配套 |
| **SQLAlchemy** | Python ORM 库 |
| **Alembic** | SQLAlchemy 的数据库迁移工具 |
| **Uvicorn** | ASGI 服务器，开发用 |
| **Gunicorn** | WSGI/ASGI 服务器，生产用 |
| **Middleware** | 中间件，拦截请求/响应做统一处理 |

### 数据库

| 术语 | 含义 |
|:----:|:----|
| **SQLite** | 轻量级文件数据库，开发用 |
| **PostgreSQL** | 开源关系数据库，生产推荐 |
| **DDL** | Data Definition Language（CREATE/ALTER/DROP） |
| **DML** | Data Manipulation Language（INSERT/UPDATE/DELETE） |
| **DQL** | Data Query Language（SELECT） |
| **索引** | Index，加速查询的数据结构 |
| **事务** | Transaction，一组操作要么全部成功要么全部失败 |
| **N+1 查询** | 性能反模式：循环里查询关联数据，应该用 JOIN 或预加载 |

### Git/DevOps

| 术语 | 含义 |
|:----:|:----|
| **PR** | Pull Request 合并请求 |
| **MR** | Merge Request（GitLab 叫法） |
| **CI** | Continuous Integration 持续集成 |
| **CD** | Continuous Delivery/Deployment 持续交付/部署 |
| **rebase** | 变基，把分支提交移到新基础上 |
| **squash** | 压缩多个 commit 为一个 |
| **hotfix** | 紧急修复，跳过常规流程 |

---

## 四、项目内部约定术语

| 术语 | 项目内含义 |
|:----:|:--------|
| **HIS-OP** | 本项目的代号（Hospital Outpatient Information Management System） |
| **HOIM** | 同上，缩写 |
| **三步流程** | 现场挂号/报到/转诊的标准流程：身份证 → 选项卡片 → 成功 |
| **page-toolbar** | 全局工具类，定义页面顶部操作栏样式 |
| **maskIdentity** | 前端工具函数，身份证脱敏（370101********1234） |
| **operation log middleware** | 操作日志中间件，自动记录 POST/PUT/DELETE |
| **statusText** | API 响应中的状态文本字段（如"未就诊"），由后端 status_map 映射 |

---

## 五、术语贡献

发现新术语或术语错误？请：

1. 在本文档对应位置添加
2. 按字母/拼音顺序排列
3. 提 PR 时类型用 `docs(glossary)`

