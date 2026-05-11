# 医院门诊信息管理系统数据库文档

## 概述

本系统使用 PostgreSQL / SQLite 数据库，通过 SQLAlchemy ORM 进行数据建模。所有表名均以 `hoimsystem_` 为前缀。

> **状态标识说明**：
> - ✅ **已建表** — 当前代码中已存在该表
> - 📋 **规划中** — 根据需求文档规划的新增表，待后续迭代建表

---

## 表结构

### 1. hoimsystem_users（用户表）✅

存储系统登录用户基本信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| user_id | INT | - | PK, AI | 用户 ID |
| username | VARCHAR | 20 | - | 登录用户名 |
| password | VARCHAR | 128 | - | 登录密码（bcrypt加密存储） |
| user_role | VARCHAR | 10 | - | 用户角色：admin / doctor / director / patient |

**关联关系：**
- 一对多 → `hoimsystem_notice`（writer_id）
- 一对多 → `hoimsystem_doctor`（user_id）
- 一对多 → `hoimsystem_operation_log`（user_id）

---

### 2. hoimsystem_patient（病人表）✅

存储病人基本信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| patient_id | INT | - | PK, AI | 病人 ID |
| name | VARCHAR | 24 | - | 姓名 |
| sex | INT | - | - | 性别（0=女，1=男） |
| identity | VARCHAR | 20 | - | 身份证号 |
| birthday | DATE | - | - | 生日 |
| phone | VARCHAR | 11 | - | 手机号 |
| address | VARCHAR | 100 | - | 地址 |
| permission | VARCHAR | 10 | - | 权限状态 |
| allergy_history | VARCHAR | 200 | - | 过敏史 |
| prepaid_balance | FLOAT | - | - | 预交金余额 |

**关联关系：**
- 一对多 → `hoimsystem_registration`（patient_id）
- 一对多 → `hoimsystem_appointment`（patient_id）
- 一对多 → `hoimsystem_prescription`（patient_id）
- 一对多 → `hoimsystem_medical_record`（patient_id）
- 一对多 → `hoimsystem_vital_sign`（patient_id）

> 注：`allergy_history` 字段为规划中新增。

---

### 3. hoimsystem_doctor（医生表）✅

存储医生基本信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| doctor_id | INT | - | PK, AI | 医生 ID |
| name | VARCHAR | 24 | - | 姓名 |
| sex | INT | - | - | 性别（0=女，1=男） |
| department_id | INT | - | FK | 所属科室 ID |
| title | VARCHAR | 10 | - | 职称 |
| education | VARCHAR | 10 | - | 学历 |
| phone | VARCHAR | 11 | - | 手机号 |
| permission | VARCHAR | 10 | - | 权限状态 |
| user_id | INT | - | FK | 关联用户 ID |

**关联关系：**
- 多对一 → `hoimsystem_department`（department_id）
- 多对一 → `hoimsystem_users`（user_id）
- 一对多 → `hoimsystem_doctor_schedule`（doctor_id）
- 一对多 → `hoimsystem_registration`（doctor_id）
- 一对多 → `hoimsystem_appointment`（doctor_id）
- 一对多 → `hoimsystem_prescription`（doctor_id）
- 一对多 → `hoimsystem_medical_record`（doctor_id）

---

### 4. hoimsystem_department（科室表）✅

存储科室信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| department_id | INT | - | PK, AI | 科室 ID |
| name | VARCHAR | 24 | - | 科室名称 |
| phone | VARCHAR | 11 | - | 科室电话 |
| location | VARCHAR | 24 | - | 科室位置 |
| director | INT | - | - | 主任医生 ID |

**关联关系：**
- 一对多 → `hoimsystem_doctor`（department_id）

---

### 5. hoimsystem_timeslot（时段表）✅

存储预约/挂号时段定义。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| timeslot_id | INT | - | PK, AI | 时段 ID |
| time | VARCHAR | 20 | - | 时段描述 |

---

### 6. hoimsystem_notice（通知公告表）✅

存储系统通知和公告。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| notice_id | VARCHAR | 36 | PK | 通知 UUID |
| title | VARCHAR | 12 | - | 标题 |
| content | TEXT | - | - | 内容 |
| isemergency | INT | - | - | 是否紧急（0=否，1=是） |
| towho | VARCHAR | 100 | - | 目标人群 |
| sendtime | DATETIME | - | - | 发送时间 |
| expiredtime | DATETIME | - | - | 过期时间 |
| readnum | INT | - | - | 阅读次数 |
| writer_id | INT | - | FK | 发布人用户 ID |

**关联关系：**
- 多对一 → `hoimsystem_users`（writer_id）

---

### 7. hoimsystem_doctor_schedule（医生排班表）✅

存储医生每周排班及号源信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| schedule_id | INT | - | PK, AI | 排班 ID |
| week | VARCHAR | 5 | - | 星期（如"星期一"） |
| time | VARCHAR | 2 | - | 时段编号 |
| number | INT | - | - | 剩余号源数 |
| specialist | INT | - | - | 是否专家号（0=否，1=是） |
| doctor_id | INT | - | FK | 医生 ID |

**关联关系：**
- 多对一 → `hoimsystem_doctor`（doctor_id）

---

### 8. hoimsystem_registration（挂号表）✅

存储病人挂号记录。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| registration_uuid | VARCHAR | 36 | PK | 挂号 UUID |
| registration_id | INT | - | - | 挂号序号 |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |
| specialist | INT | - | - | 是否专家号 |
| department_id | INT | - | FK | 科室 ID |
| time | DATETIME | - | - | 挂号时间 |
| status | INT | - | - | 状态（0=未就诊，1=已就诊，3=已取消） |

**关联关系：**
- 多对一 → `hoimsystem_patient`（patient_id）
- 多对一 → `hoimsystem_doctor`（doctor_id）
- 多对一 → `hoimsystem_department`（department_id）

---

### 9. hoimsystem_appointment（预约表）✅

存储病人预约记录。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| registration_uuid | VARCHAR | 36 | PK | 预约 UUID |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |
| specialist | INT | - | - | 是否专家号 |
| department_id | INT | - | FK | 科室 ID |
| prefer_time | VARCHAR | 5 | - | 偏好时段 |
| appointment_time | DATETIME | - | - | 预约提交时间 |
| time | DATE | - | - | 预约日期 |
| status | INT | - | - | 状态（0=未就诊，1=已就诊，2=已取消） |

**关联关系：**
- 多对一 → `hoimsystem_patient`（patient_id）
- 多对一 → `hoimsystem_doctor`（doctor_id）
- 多对一 → `hoimsystem_department`（department_id）

---

### 10. hoimsystem_breach_record（违约记录表）✅

存储病人违约记录。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| breach_id | VARCHAR | 36 | PK | 违约记录 UUID |
| registration_id | VARCHAR | 36 | FK | 关联挂号 UUID |
| breach_time | DATETIME | - | - | 违约时间 |
| breach_type | VARCHAR | 20 | - | 违约类型 |

---

### 11. hoimsystem_charge（收费表）✅

存储处方收费记录。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| charge_id | VARCHAR | 36 | PK | 收费记录 UUID |
| charge_time | DATETIME | - | - | 收费创建时间 |
| time | DATETIME | - | - | 实际缴费时间 |
| prescription_id | VARCHAR | 36 | FK | 处方 ID |
| amount | FLOAT | - | - | 收费金额 |
| status | INT | - | - | 状态（0=未缴费，1=已缴费，2=已退费） |

**关联关系：**
- 多对一 → `hoimsystem_prescription`（prescription_id）

> 注：`status` 字段扩展：2=已退费。

---

### 12. hoimsystem_prescription（处方表）✅

存储医生开具的处方信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| prescription_id | VARCHAR | 36 | PK | 处方 UUID |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |
| status | INT | - | - | 处方状态（0=待审核，1=已审核，2=已发药，3=已取消） |
| create_time | DATETIME | - | - | 创建时间 |

**关联关系：**
- 多对一 → `hoimsystem_patient`（patient_id）
- 多对一 → `hoimsystem_doctor`（doctor_id）
- 一对多 → `hoimsystem_charge`（prescription_id）
- 一对多 → `hoimsystem_pre_pha`（prescription_id）

> 注：`status` 和 `create_time` 为规划中新增字段。

---

### 13. hoimsystem_pre_pha（处方药品关联表）✅

存储处方与药品的关联关系。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| pre_pha_id | VARCHAR | 36 | PK | 关联记录 UUID |
| prescription_id | VARCHAR | 50 | - | 处方 ID |
| pharmaceutical_id | INT | - | FK | 药品 ID |
| number | INT | - | - | 药品数量 |

**关联关系：**
- 多对一 → `hoimsystem_pharmaceutical`（pharmaceutical_id）
- 多对一 → `hoimsystem_prescription`（prescription_id）

---

### 14. hoimsystem_medical_record（病历表）✅

存储病人病历信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| medical_record_id | VARCHAR | 36 | PK | 病历 UUID |
| consultation_time | DATETIME | - | - | 就诊时间 |
| doctor_id | INT | - | FK | 医生 ID |
| patient_id | INT | - | FK | 病人 ID |
| symptom | VARCHAR | 100 | - | 症状描述 |
| result | VARCHAR | 100 | - | 诊断结果 |
| registration_uuid | VARCHAR | 36 | FK | 关联挂号/预约 ID |

**关联关系：**
- 多对一 → `hoimsystem_doctor`（doctor_id）
- 多对一 → `hoimsystem_patient`（patient_id）

> 注：`registration_uuid` 为规划中新增字段。

---

### 15. hoimsystem_pharmaceutical（药品表）✅

存储药品库存信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| pharmaceutical_id | INT | - | PK, AI | 药品 ID |
| name | VARCHAR | 24 | - | 药品名称 |
| stock | INT | - | - | 库存数量 |
| price | FLOAT | - | - | 单价 |
| expireddate | DATE | - | - | 过期日期 |
| purchasing_time | DATETIME | - | - | 采购时间 |
| supplier | VARCHAR | 24 | - | 供应商 |
| remark | VARCHAR | 100 | - | 备注 |
| status | INT | - | - | 状态（0=正常，1=停用） |
| antibiotic_level | INT | - | - | 抗菌级别（0=非抗菌 1=非限制 2=限制 3=特殊） |

> 注：`status`、`antibiotic_level` 为新增字段。

---

## 扩展功能表（已建表）

---

### 16. hoimsystem_queue（候诊队列表）✅

存储候诊叫号队列信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| queue_id | INT | - | PK, AI | 队列 ID |
| queue_number | INT | - | - | 排队序号 |
| registration_uuid | VARCHAR | 36 | FK | 关联挂号/预约 ID |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |
| type | INT | - | - | 类型（0=现场挂号，1=预约） |
| status | INT | - | - | 状态（0=候诊，1=叫号中，2=已过号，3=已就诊） |
| call_time | DATETIME | - | - | 叫号时间 |
| create_time | DATETIME | - | - | 入队时间 |

---

### 17. hoimsystem_vital_sign（生命体征表）✅

存储护士预检时录入的生命体征数据。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| vital_id | INT | - | PK, AI | 记录 ID |
| patient_id | INT | - | FK | 病人 ID |
| nurse_id | INT | - | FK | 护士用户 ID |
| temperature | FLOAT | - | - | 体温（摄氏度） |
| blood_pressure_systolic | INT | - | - | 收缩压（mmHg） |
| blood_pressure_diastolic | INT | - | - | 舒张压（mmHg） |
| pulse | INT | - | - | 脉搏（次/分） |
| weight | FLOAT | - | - | 体重（kg） |
| check_time | DATETIME | - | - | 测量时间 |

---

### 18. hoimsystem_lab_order（检查申请单表）✅

存储医生开具的检查检验申请单。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| lab_order_id | VARCHAR | 36 | PK | 申请单 UUID |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |
| check_type | VARCHAR | 20 | - | 检查类型 |
| check_items | VARCHAR | 200 | - | 检查项目（JSON 数组） |
| urgent | INT | - | - | 是否紧急（0=否，1=是） |
| status | INT | - | - | 状态（0=待缴费，1=待检查，2=已完成） |
| create_time | DATETIME | - | - | 申请时间 |

---

### 19. hoimsystem_lab_result（检查结果表）✅

存储检查检验结果。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| lab_result_id | VARCHAR | 36 | PK | 结果 UUID |
| lab_order_id | VARCHAR | 36 | FK | 申请单 ID |
| sample_id | VARCHAR | 20 | - | 样本编号 |
| result | TEXT | - | - | 检查结果 |
| abnormal_flag | INT | - | - | 是否异常（0=否，1=是） |
| technician_id | INT | - | FK | 技师用户 ID |
| report_time | DATETIME | - | - | 报告时间 |
| audit_status | INT | - | - | 审核状态（0=待审核，1=已审核） |

---

### 20. hoimsystem_invoice（发票记录表）✅

存储收费发票信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| invoice_id | VARCHAR | 36 | PK | 发票 UUID |
| charge_id | VARCHAR | 36 | FK | 收费记录 ID |
| invoice_no | VARCHAR | 24 | - | 发票号码 |
| amount | FLOAT | - | - | 金额 |
| tax | FLOAT | - | - | 税额 |
| invoice_time | DATETIME | - | - | 开票时间 |
| status | INT | - | - | 状态（0=正常，1=已作废） |

---

### 21. hoimsystem_follow_up（随访计划表）✅

存储随访计划与记录。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| follow_up_id | INT | - | PK, AI | 随访 ID |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |
| plan_date | DATE | - | - | 计划随访日期 |
| content | VARCHAR | 200 | - | 随访内容 |
| status | INT | - | - | 状态（0=待随访，1=已完成） |
| result | VARCHAR | 200 | - | 随访结果 |
| patient_feedback | VARCHAR | 200 | - | 病人反馈 |
| create_time | DATETIME | - | - | 创建时间 |

---

### 22. hoimsystem_review（满意度评价表）✅

存储病人就诊后的满意度评价。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| review_id | INT | - | PK, AI | 评价 ID |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |
| visit_id | VARCHAR | 36 | - | 就诊记录 ID |
| score | INT | - | - | 评分（1-5） |
| comment | VARCHAR | 500 | - | 评价内容 |
| review_time | DATETIME | - | - | 评价时间 |

---

### 23. hoimsystem_operation_log（操作日志表）✅

存储系统操作审计日志。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| log_id | INT | - | PK, AI | 日志 ID |
| user_id | INT | - | FK | 操作用户 ID |
| action | VARCHAR | 50 | - | 操作类型 |
| target | VARCHAR | 100 | - | 操作对象 |
| result | VARCHAR | 20 | - | 操作结果 |
| ip | VARCHAR | 40 | - | IP 地址 |
| create_time | DATETIME | - | - | 操作时间 |

---

### 24. hoimsystem_dict（数据字典表）✅

存储系统数据字典。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| dict_id | INT | - | PK, AI | 字典 ID |
| dict_type | VARCHAR | 20 | - | 字典类型 |
| dict_code | VARCHAR | 20 | - | 字典编码 |
| dict_value | VARCHAR | 50 | - | 字典值 |
| sort_order | INT | - | - | 排序号 |
| status | INT | - | - | 状态（0=启用，1=停用） |

---

### 25. hoimsystem_config（系统参数表）✅

存储系统运行参数。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| config_id | INT | - | PK, AI | 参数 ID |
| config_key | VARCHAR | 50 | - | 参数键 |
| config_value | VARCHAR | 200 | - | 参数值 |
| description | VARCHAR | 200 | - | 参数说明 |

---

## ER 关系图（文字描述）

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  hoimsystem_    │1   *│  hoimsystem_    │*   1│  hoimsystem_    │
│  users          │─────│  notice         │─────│  (writer)       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │1                                          │1
         │                                           │
         │*                                          │*
┌────────┴────────┐                          ┌──────┴──────┐
│  hoimsystem_    │                          │ hoimsystem_ │
│  doctor         │                          │   patient   │
└────────┬────────┘                          └──────┬──────┘
         │*                                         │1
         │                                          │
         │*                    ┌─────────────────┐   │*
         ├─────────────────────│  hoimsystem_    │   │
         │                     │  department     │   │
         │*   1                └─────────────────┘   │
         │                                            │
         │*                    ┌─────────────────┐    │*
         ├─────────────────────│  hoimsystem_    │◄───┘
         │                     │  medical_record │
         │                     └─────────────────┘
         │
         │*                    ┌─────────────────┐
         ├─────────────────────│  hoimsystem_    │
         │                     │  prescription   │
         │                     └─────────────────┘
         │*   1                    │1
         │                         │
         │                         │*
         │                    ┌────┴────────────┐     ┌─────────────────┐
         │                    │  hoimsystem_    │1   *│  hoimsystem_    │
         │                    │  pre_pha        │─────│  pharmaceutical │
         │                    └─────────────────┘     └─────────────────┘
         │                         │1
         │                         │
         │                         │*
         │                    ┌────┴────────────┐
         │                    │  hoimsystem_    │
         │                    │  charge         │
         │                    └─────────────────┘
         │
         │*                    ┌─────────────────┐
         ├─────────────────────│  hoimsystem_    │
         │                     │  doctor_schedule│
         │                     └─────────────────┘
         │
         │*                    ┌─────────────────┐     ┌─────────────────┐
         ├─────────────────────│  hoimsystem_    │     │  hoimsystem_    │
         │                     │  registration   │     │  appointment    │
         │                     └─────────────────┘     └─────────────────┘
         │                          │*   1                   │*   1
         │                          │                        │
         │                          │*                       │*
         │                     ┌────┴────────────────────────┴────┐
         │                     │      hoimsystem_queue            │
         │                     │      (候诊队列)                  │
         │                     └──────────────────────────────────┘

新增表（规划中）：
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  hoimsystem_    │     │  hoimsystem_    │     │  hoimsystem_    │
│  vital_sign     │     │  lab_order      │     │  lab_result     │
│  (生命体征)     │     │  (检查申请)     │     │  (检查结果)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  hoimsystem_    │     │  hoimsystem_    │     │  hoimsystem_    │
│  invoice        │     │  follow_up      │     │  review         │
│  (发票)         │     │  (随访)         │     │  (评价)         │
└─────────────────┘     └─────────────────┘     └─────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  hoimsystem_    │     │  hoimsystem_    │     │  hoimsystem_    │
│  operation_log  │     │  dict           │     │  config         │
│  (操作日志)     │     │  (数据字典)     │     │  (系统参数)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## 建表状态汇总

| 序号 | 表名 | 中文名 | 状态 | 说明 |
|:----:|:-----|:------:|:----:|:----:|
| 1 | hoimsystem_users | 用户表 | ✅ | |
| 2 | hoimsystem_patient | 病人表 | ✅ | 新增 allergy_history |
| 3 | hoimsystem_doctor | 医生表 | ✅ | |
| 4 | hoimsystem_department | 科室表 | ✅ | |
| 5 | hoimsystem_timeslot | 时段表 | ✅ | |
| 6 | hoimsystem_notice | 通知公告表 | ✅ | |
| 7 | hoimsystem_doctor_schedule | 医生排班表 | ✅ | |
| 8 | hoimsystem_registration | 挂号表 | ✅ | |
| 9 | hoimsystem_appointment | 预约表 | ✅ | |
| 10 | hoimsystem_breach_record | 违约记录表 | ✅ | |
| 11 | hoimsystem_charge | 收费表 | ✅ | 扩展 status |
| 12 | hoimsystem_prescription | 处方表 | ✅ | 新增 status、create_time |
| 13 | hoimsystem_pre_pha | 处方药品关联表 | ✅ | |
| 14 | hoimsystem_medical_record | 病历表 | ✅ | 新增 registration_uuid |
| 15 | hoimsystem_pharmaceutical | 药品表 | ✅ | 新增 status |
| 16 | hoimsystem_queue | 候诊队列表 | ✅ | 新增 |
| 17 | hoimsystem_vital_sign | 生命体征表 | ✅ | 新增 |
| 18 | hoimsystem_lab_order | 检查申请单表 | ✅ | 新增 |
| 19 | hoimsystem_lab_result | 检查结果表 | ✅ | 新增 |
| 20 | hoimsystem_invoice | 发票记录表 | ✅ | 新增 |
| 21 | hoimsystem_follow_up | 随访计划表 | ✅ | 新增 |
| 22 | hoimsystem_review | 满意度评价表 | ✅ | 新增 |
| 23 | hoimsystem_operation_log | 操作日志表 | ✅ | 新增 |
| 24 | hoimsystem_dict | 数据字典表 | ✅ | 新增 |
| 25 | hoimsystem_config | 系统参数表 | ✅ | 新增 |
| 26 | hoimsystem_attendance | 考勤记录表 | ✅ | 新增 |
| 27 | hoimsystem_patrol_record | 巡视记录表 | ✅ | 新增 |
| 28 | hoimsystem_message | 消息记录表 | ✅ | 新增 |
| 29 | hoimsystem_payment | 支付流水表 | ✅ | 新增 |
| 30 | hoimsystem_triage_record | 分诊记录表 | ✅ | 新增 |
| 31 | hoimsystem_consumable | 耗材表 | ✅ | 新增 |
| 32 | hoimsystem_purchase_order | 采购订单表 | ✅ | 新增 |
| 33 | hoimsystem_purchase_order_item | 采购明细表 | ✅ | 新增 |
| 34 | hoimsystem_adverse_reaction | 不良反应表 | ✅ | 新增 |
| 35 | hoimsystem_adverse_event | 不良事件表 | ✅ | 新增 |
| 36 | hoimsystem_referral | 转诊记录表 | ✅ | 新增 |
| 37 | hoimsystem_mdt_case | MDT会诊表 | ✅ | 新增 |
| 38 | hoimsystem_clinical_pathway | 临床路径表 | ✅ | 新增 |
