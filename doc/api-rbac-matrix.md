# HOIMSystem API 角色访问矩阵 (RBAC Matrix)

> 基于源码静态分析生成。每个 API 强制校验 `accesstoken`。

> `✓`=可访问 | `PUBLIC`=无需登录 | 留空=不可访问


## 角色定义

| 角色 | 常量 | 说明 |
|------|------|------|
| `admin` | `ROLE_ADMIN` | 系统管理员 |
| `super_admin` | `ROLE_SUPER_ADMIN` | 超级管理员 |
| `director` | `ROLE_DIRECTOR` | 科室主任 |
| `doctor` | `ROLE_DOCTOR` | 医生 |
| `nurse` | `ROLE_NURSE` | 护士 |
| `cashier` | `ROLE_CASHIER` | 收费员 |
| `pharmacist` | `ROLE_PHARMACIST` | 药师 |
| `guide` | `ROLE_GUIDE` | 导诊员 |
| `patient` | `ROLE_PATIENT` | 患者 |
| `lab_technician` | `ROLE_LAB_TECHNICIAN` | 检验技师 |
| `registrar` | `ROLE_REGISTRAR` | 挂号员 |

## 角色组常量

| 常量 | 包含角色 |
|------|----------|
| `ADMIN_ROLES` | `admin`, `super_admin` |
| `CLINICAL_ROLES` | `admin`, `super_admin`, `director`, `doctor` |
| `CASHIER_ROLES` | `admin`, `super_admin`, `cashier` |
| `PHARMACY_ROLES` | `admin`, `super_admin`, `pharmacist` |
| `NURSING_ROLES` | `admin`, `super_admin`, `nurse` |
| `GUIDE_ROLES` | `admin`, `super_admin`, `guide` |
| `LAB_ROLES` | `admin`, `super_admin`, `lab_technician` |
| `get_current_user` | 任意已登录用户 (全部 11 种) |

## API 矩阵 (247 个接口)

### 管理员(医生/患者/科室/公告) (`admin.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/doctorManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/doctorManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/doctorManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/patientManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/patientManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/departmentManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/departmentManagement/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/departmentManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/departmentManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/notice/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/notice/create` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/notice/update` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/notice/delete` |  |  |  |  |  |  |  |  |  |  |  | |

### 入院登记 (`admission.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/admission/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/admission/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| GET | `/api/admission/detail` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| POST | `/api/admission/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| GET | `/api/admission/getAvailableBeds` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| GET | `/api/admission/getInpatientList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |

### 不良事件 (`adverse_event.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/adverseEvent/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/adverseEvent/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/adverseEvent/updateStatus` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |

### 药品不良反应 (`adverse_reaction.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/adverseReaction/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/adverseReaction/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/adverseReaction/updateStatus` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |

### 数据备份 (`backup.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/backup/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/backup/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/backup/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/backup/restore` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/backup/download/{filename}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |

### 收费管理(缴费/发票/日结/窗口挂号/支付) (`charge.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/chargeManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/chargeManagement/charge` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/chargeManagement/refund` |  |  |  |  |  |  |  |  |  |  |  | |
| GET | `/api/invoice/getList` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/invoice/create` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/invoice/print` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/windowRegistration/create` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/windowRegistration/cancel` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/dailySettlement/report` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/payment/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/payment/query/{payment_no}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/payment/mockNotify` |  |  |  |  |  |  |  |  |  |  |  | |
| GET | `/api/payment/getList` |  |  |  |  |  |  |  |  |  |  |  | |

### 报到签到/违约 (`checkin.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/checkIn/getAppointments` | | | | | | | | | | | | ✓ |
| POST | `/api/checkIn/checkIn` | | | | | | | | | | | | ✓ |
| GET | `/api/breach/getList` |  |  |  |  |  |  |  |  |  |  |  | |
| GET | `/api/breach/checkSuspend` |  |  |  |  |  |  |  |  |  |  |  | |

### 临床路径 (`clinical_pathway.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/clinicalPathway/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/clinicalPathway/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/clinicalPathway/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/clinicalPathway/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |

### 耗材管理 (`consumable.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/consumable/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/consumable/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/consumable/update` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/consumable/delete` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |

### CA 数字签名 (`digital_signature.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/digitalSignature/sign` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/digitalSignature/verify` | | | | | | | | | | | | ✓ |

### 出院结算 (`discharge.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/discharge/doDischarge` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| GET | `/api/discharge/getSummary` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| POST | `/api/discharge/updateSummary` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| GET | `/api/discharge/getDischargedList` | | | | | | | | | | | | ✓ |

### 医生工作站(排班/药品/处方/病历/检验/考勤/号源) (`doctor.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/doctorManagement/register` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/doctorScheduleManagement/register` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/doctorScheduleManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/pharmaceuticalManagement/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| GET | `/api/pharmaceuticalManagement/getList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmaceuticalManagement/update` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmaceuticalManagement/delete` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmaceuticalManagement/stock_query` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| GET | `/api/pharmaceuticalManagement/lowStock` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| GET | `/api/pharmaceuticalManagement/nearExpiry` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/prescriptionManagement/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/prescriptionManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/prescriptionManagement/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/medicalRecord/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/medicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/labOrder/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/labOrder/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/attendance/checkIn` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/attendance/checkOut` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/attendance/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/slotPool/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/slotPool/adjust` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |

### 电子病历 (`emr.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/emrTemplate/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/emrTemplate/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/emrTemplate/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/emrTemplate/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/emrTemplate/detail` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/structuredMedicalRecord/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/structuredMedicalRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/structuredMedicalRecord/detail` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/structuredMedicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/structuredMedicalRecord/sign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/structuredMedicalRecord/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/progressNote/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/progressNote/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/progressNote/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/wardRound/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/wardRound/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/wardRound/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/medicalRecordQuality/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/medicalRecordQuality/check` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/medicalRecordQuality/summary` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |

### 体检中心 (`exam.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/examPackage/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/examPackage/create` | | | | | | | | | | | | ✓ |
| POST | `/api/examPackage/update` | | | | | | | | | | | | ✓ |
| POST | `/api/examPackage/delete` | | | | | | | | | | | | ✓ |
| GET | `/api/examItem/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/examItem/create` | | | | | | | | | | | | ✓ |
| POST | `/api/examItem/update` | | | | | | | | | | | | ✓ |
| POST | `/api/examItem/delete` | | | | | | | | | | | | ✓ |
| GET | `/api/examAppointment/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/examAppointment/create` | | | | | | | | | | | | ✓ |
| POST | `/api/examAppointment/updateStatus` | | | | | | | | | | | | ✓ |
| GET | `/api/examRecord/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/examRecord/create` | | | | | | | | | | | | ✓ |
| POST | `/api/examRecord/update` | | | | | | | | | | | | ✓ |
| POST | `/api/examRecord/complete` | | | | | | | | | | | | ✓ |
| GET | `/api/examResult/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/examResult/create` | | | | | | | | | | | | ✓ |
| GET | `/api/examReport/getDetail` | | | | | | | | | | | | ✓ |

### 随访 (`followup.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/followUpAppointment/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/followUp/createPlan` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/followUp/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/followUp/record` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |

### 住院费用 (`inpatient_charge.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/inpatientCharge/getList` | | | | | | | | | | | | ✓ |
| GET | `/api/inpatientCharge/getDailyBill` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/inpatientCharge/settle` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  | |
| POST | `/api/inpatientCharge/refund` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  | |
| GET | `/api/inpatientCharge/getSummary` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |

### 住院医嘱 (`inpatient_order.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/inpatientOrder/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/inpatientOrder/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/inpatientOrder/audit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/inpatientOrder/stop` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/inpatientOrder/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/inpatientOrder/getExecutionList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/inpatientOrder/execute` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |

### 检验科 (`lab.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/lab/sampleReceive` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |
| POST | `/api/lab/sampleReject` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |
| GET | `/api/lab/sampleTracking` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |
| POST | `/api/labResult/create` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |
| POST | `/api/labResult/audit` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |
| GET | `/api/labResult/getPending` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |
| GET | `/api/labResult/getList` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |
| POST | `/api/labResult/detail` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  | |

### 多学科会诊 (`mdt.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/mdt/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/mdt/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/mdt/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |

### 护士工作站 (`nursing.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/nursingRecord/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/nursingRecord/create` | | | | | | | | | | | | ✓ |
| POST | `/api/nursingRecord/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| GET | `/api/temperatureRecord/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/temperatureRecord/create` | | | | | | | | | | | | ✓ |
| POST | `/api/temperatureRecord/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |

### 患者服务(预约/挂号/病历/健康档案/评价) (`patient.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/appointmentManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/appointmentManagement/appointmentList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/appointmentManagement/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/appointmentManagement/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/registrationManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/registrationManagement/registrationList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/registrationManagement/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/registrationManagement/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/medicalRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/medicalRecord/detail` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/healthRecord/getProfile` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/healthRecord/getVisits` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/review/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |

### 药房(发药/审核/退药/盘点/点评) (`pharmacy.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/pharmacy/dispenseList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmacy/audit` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmacy/dispense` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmacy/return` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmacy/stockCheck` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| POST | `/api/pharmacy/review` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |
| GET | `/api/pharmacy/reviewList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  | |

### 药品采购 (`purchase.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/purchase/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/purchase/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/purchase/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/purchase/storage` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/purchase/cancel` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |

### 排队叫号 (`queue.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/queue/emergency` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/queue/reorder` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/queue/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/queue/callNext` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/queue/pass` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/queue/skip` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/patrol/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/patrol/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |

### 双向转诊 (`referral.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/referral/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/referral/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/referral/updateStatus` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |

### 报表统计 (`report.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/report/outpatientVolume` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/report/finance` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/report/pharmaceutical` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/report/doctorWorkload` |  |  |  |  |  |  |  |  |  |  |  | |

### 手术管理 (`surgery.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/surgeryApplication/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/surgeryApplication/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/surgeryApplication/approve` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/surgeryApplication/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/surgerySchedule/getList` | | | | | | | | | | | | ✓ |
| POST | `/api/surgerySchedule/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/surgerySchedule/start` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| POST | `/api/surgerySchedule/complete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |
| GET | `/api/anesthesiaRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/anesthesiaRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  | |

### 系统平台(日志/字典/配置/消息) (`system.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/log/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/dict/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/dict/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/dict/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/dict/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/config/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/config/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| POST | `/api/message/send` | ✓ | ✓ |  |  |  |  |  |  |  |  |  | |
| GET | `/api/message/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/message/read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |

### 智能导诊 (`triage.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/triage/suggest` | | | | | | | | | | | | ✓ |
| GET | `/api/triage/keywords` | | | | | | | | | | | | ✓ |

### 分诊台 (`triage_desk.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/triageDesk/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/triageDesk/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/triageDesk/updateStatus` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  | |
| POST | `/api/triageDesk/update` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  | |

### 文件上传 (`upload.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/upload/avatar` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/upload/report` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/uploads/avatars/{filename}` | | | | | | | | | | | | ✓ |
| GET | `/api/uploads/reports/{filename}` | | | | | | | | | | | | ✓ |

### 用户认证 (`user.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/test` | | | | | | | | | | | | ✓ |
| GET | `/api/publicKey` | | | | | | | | | | | | ✓ |
| POST | `/api/login` | | | | | | | | | | | | ✓ |
| POST | `/api/register` | | | | | | | | | | | | ✓ |
| POST | `/api/userInfo` | | | | | | | | | | | | ✓ |
| POST | `/api/logout` | | | | | | | | | | | | ✓ |
| GET | `/api/user/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/user/updateRole` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/user/resetPassword` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/user/delete` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| GET | `/api/prepaid/getBalance` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |
| POST | `/api/prepaid/recharge` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/prepaid/deduct` |  |  |  |  |  |  |  |  |  |  |  | |

### 生命体征 (`vitalsign.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| POST | `/api/vitalSign/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  | |
| GET | `/api/vitalSign/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | |

### 病区床位 (`ward.py`)

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|---|---|---|---|---|---|---|---|---|---|---|------|
| GET | `/api/ward/getList` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/ward/create` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/ward/update` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/ward/delete` |  |  |  |  |  |  |  |  |  |  |  | |
| GET | `/api/bed/getList` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/bed/create` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/bed/update` |  |  |  |  |  |  |  |  |  |  |  | |
| POST | `/api/bed/delete` |  |  |  |  |  |  |  |  |  |  |  | |


## 公开接口清单(无需登录)

| 方法 | 路径 |
|------|------|
| GET | `/api/admission/getList` |
| GET | `/api/checkIn/getAppointments` |
| POST | `/api/checkIn/checkIn` |
| GET | `/api/consumable/getList` |
| POST | `/api/digitalSignature/verify` |
| GET | `/api/discharge/getDischargedList` |
| GET | `/api/examPackage/getList` |
| POST | `/api/examPackage/create` |
| POST | `/api/examPackage/update` |
| POST | `/api/examPackage/delete` |
| GET | `/api/examItem/getList` |
| POST | `/api/examItem/create` |
| POST | `/api/examItem/update` |
| POST | `/api/examItem/delete` |
| GET | `/api/examAppointment/getList` |
| POST | `/api/examAppointment/create` |
| POST | `/api/examAppointment/updateStatus` |
| GET | `/api/examRecord/getList` |
| POST | `/api/examRecord/create` |
| POST | `/api/examRecord/update` |
| POST | `/api/examRecord/complete` |
| GET | `/api/examResult/getList` |
| POST | `/api/examResult/create` |
| GET | `/api/examReport/getDetail` |
| GET | `/api/inpatientCharge/getList` |
| GET | `/api/inpatientOrder/getList` |
| GET | `/api/nursingRecord/getList` |
| POST | `/api/nursingRecord/create` |
| GET | `/api/temperatureRecord/getList` |
| POST | `/api/temperatureRecord/create` |
| GET | `/api/surgeryApplication/getList` |
| GET | `/api/surgerySchedule/getList` |
| POST | `/api/triage/suggest` |
| GET | `/api/triage/keywords` |
| GET | `/api/uploads/avatars/{filename}` |
| GET | `/api/uploads/reports/{filename}` |
| POST | `/api/test` |
| GET | `/api/publicKey` |
| POST | `/api/login` |
| POST | `/api/register` |
| POST | `/api/userInfo` |
| POST | `/api/logout` |