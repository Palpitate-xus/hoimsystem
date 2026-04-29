# 医院门诊信息管理系统数据库文档

## 概述

本系统使用 MySQL 数据库，通过 SQLAlchemy ORM 进行数据建模。所有表名均以 `hoimsystem_` 为前缀。

---

## 表结构

### 1. hoimsystem_users（用户表）

存储系统登录用户基本信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| user_id | INT | - | PK, AI | 用户 ID |
| username | VARCHAR | 20 | - | 登录用户名 |
| password | VARCHAR | 20 | - | 登录密码（明文存储） |
| user_role | VARCHAR | 10 | - | 用户角色：admin / doctor / director / patient |

**关联关系：**
- 一对多 → `hoimsystem_notice`（writer_id）
- 一对多 → `hoimsystem_doctor`（user_id）

---

### 2. hoimsystem_patient（病人表）

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

**关联关系：**
- 一对多 → `hoimsystem_registration`（patient_id）
- 一对多 → `hoimsystem_appointment`（patient_id）
- 一对多 → `hoimsystem_prescription`（patient_id）
- 一对多 → `hoimsystem_medical_record`（patient_id）

---

### 3. hoimsystem_doctor（医生表）

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

### 4. hoimsystem_department（科室表）

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

### 5. hoimsystem_timeslot（时段表）

存储预约/挂号时段定义。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| timeslot_id | INT | - | PK, AI | 时段 ID |
| time | VARCHAR | 20 | - | 时段描述 |

---

### 6. hoimsystem_notice（通知公告表）

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

### 7. hoimsystem_doctor_schedule（医生排班表）

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

### 8. hoimsystem_registration（挂号表）

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

### 9. hoimsystem_appointment（预约表）

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

### 10. hoimsystem_breach_record（违约记录表）

存储病人违约记录。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| breach_id | VARCHAR | 36 | PK | 违约记录 UUID |
| registration_id | VARCHAR | 36 | FK | 关联挂号 UUID |

---

### 11. hoimsystem_charge（收费表）

存储处方收费记录。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| charge_id | VARCHAR | 36 | PK | 收费记录 UUID |
| charge_time | DATETIME | - | - | 收费创建时间 |
| time | DATETIME | - | - | 实际缴费时间 |
| prescription_id | VARCHAR | 36 | FK | 处方 ID |
| amount | FLOAT | - | - | 收费金额 |
| status | INT | - | - | 状态（0=未缴费，1=已缴费） |

**关联关系：**
- 多对一 → `hoimsystem_prescription`（prescription_id）

---

### 12. hoimsystem_prescription（处方表）

存储医生开具的处方信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| prescription_id | VARCHAR | 36 | PK | 处方 UUID |
| patient_id | INT | - | FK | 病人 ID |
| doctor_id | INT | - | FK | 医生 ID |

**关联关系：**
- 多对一 → `hoimsystem_patient`（patient_id）
- 多对一 → `hoimsystem_doctor`（doctor_id）
- 一对多 → `hoimsystem_charge`（prescription_id）
- 一对多 → `hoimsystem_pre_pha`（prescription_id）

---

### 13. hoimsystem_pre_pha（处方药品关联表）

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

### 14. hoimsystem_medical_record（病历表）

存储病人病历信息。

| 字段名 | 类型 | 长度 | 约束 | 说明 |
|:------:|:----:|:----:|:----:|:----:|
| medical_record_id | VARCHAR | 36 | PK | 病历 UUID |
| consultation_time | DATETIME | - | - | 就诊时间 |
| doctor_id | INT | - | FK | 医生 ID |
| patient_id | INT | - | FK | 病人 ID |
| symptom | VARCHAR | 100 | - | 症状描述 |
| result | VARCHAR | 100 | - | 诊断结果 |

**关联关系：**
- 多对一 → `hoimsystem_doctor`（doctor_id）
- 多对一 → `hoimsystem_patient`（patient_id）

---

### 15. hoimsystem_pharmaceutical（药品表）

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

---

## ER 关系图（文字描述）

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  hoimsystem_    │1   *│  hoimsystem_    │*   1│  hoimsystem_    │
│  users          │─────│  notice         │─────│  (writer)       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │1
         │
         │*
┌─────────────────┐
│  hoimsystem_    │
│  doctor         │
└─────────────────┘
         │*                    ┌─────────────────┐
         │                     │  hoimsystem_    │
         ├─────────────────────│  department     │
         │*   1                └─────────────────┘
         │
         │*                    ┌─────────────────┐     ┌─────────────────┐
         ├─────────────────────│  hoimsystem_    │1   *│  hoimsystem_    │
         │                     │  prescription   │─────│  pre_pha        │
         │                     └─────────────────┘     └─────────────────┘
         │*   1                    │1                        │*
         │                         │                        │
         │                         │*                       │1
         │                    ┌─────────────────┐     ┌─────────────────┐
         │                    │  hoimsystem_    │     │  hoimsystem_    │
         │                    │  charge         │     │  pharmaceutical │
         │                    └─────────────────┘     └─────────────────┘
         │
         │*                    ┌─────────────────┐
         ├─────────────────────│  hoimsystem_    │
         │                     │  medical_record │
         │                     └─────────────────┘
         │
         │*
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  hoimsystem_    │1   *│  hoimsystem_    │     │  hoimsystem_    │
│  patient        │─────│  registration   │     │  doctor_schedule│
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │*                    │*   1
         │                     │
         │*                    │*
         └─────────────────────┘
              hoimsystem_appointment
```
