# HOIMSystem API 角色访问矩阵 (RBAC Matrix)

> 由 `fastapi_be/scripts/generate_rbac_matrix.py` 从源码自动生成，请勿手改。
> `✓`=可访问 | `PUBLIC`=无需登录 | 留空=不可访问

共 **484** 个接口（PUBLIC 14 个 / 需登录 470 个）。


### `admin.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/campusManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/campusManagement/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/campusManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/campusManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/doctorManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/doctorManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/doctorManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/patientManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/patientManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/departmentManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/departmentManagement/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/departmentManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/departmentManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/notice/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/notice/create` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/notice/update` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/notice/delete` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `admission.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/admission/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/admission/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/admission/detail` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/admission/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/admission/getAvailableBeds` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/admission/getInpatientList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `adverse_event.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/adverseEvent/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/adverseEvent/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/adverseEvent/updateStatus` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `adverse_reaction.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/adverseReaction/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/adverseReaction/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/adverseReaction/updateStatus` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `allergy.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/allergy/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/allergy/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| PUT | `/api/allergy/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/allergy/disable` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `antibiotic.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/antibiotic/grade/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/antibiotic/grade/save` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/antibiotic/approval/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/antibiotic/approval/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/antibiotic/approval/review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/antibiotic/ddds` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/antibiotic/submissionRate` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `backup.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/backup/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/backup/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/backup/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/backup/restore` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/backup/download/{filename}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `blood.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/blood/request/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/blood/request/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/blood/request/review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/blood/recheck` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/blood/crossMatch` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/blood/issue` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/blood/reaction/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/blood/reaction/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `charge.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/chargeManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/chargeManagement/charge` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/chargeManagement/refund` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/invoice/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/windowRegistration/schedules` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/windowRegistration/patient` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/windowRegistration/appointments` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/windowRegistration/appointmentConfirm` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/windowRegistration/appointmentCancel` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/invoice/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/invoice/print` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/invoice/pdf/{invoice_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/windowRegistration/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/windowRegistration/cancel` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dailySettlement/report` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/payment/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/payment/query/{payment_no}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/payment/mockNotify` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/payment/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `charge_item.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/chargeItem/list` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/chargeItem/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/chargeItem/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/chargeItem/toggle` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `checkin.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/checkIn/getAppointments` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/checkIn/checkIn` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/breach/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/breach/checkSuspend` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `clinical_pathway.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/clinicalPathway/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/clinicalPathway/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/clinicalPathway/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/clinicalPathway/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `consumable.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/consumable/getList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/consumable/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/consumable/update` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/consumable/delete` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |

### `data_import_export.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/dataImportExport/template/{entity}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dataImportExport/import/{entity}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/dataImportExport/export/{entity}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `diagnosis_template.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/diagnosisTemplate/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/diagnosisTemplate/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/diagnosisTemplate/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/diagnosisTemplate/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/diagnosisTemplate/apply` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `digital_signature.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/digitalSignature/sign` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/digitalSignature/verify` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `discharge.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/discharge/doDischarge` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/discharge/getSummary` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/discharge/updateSummary` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/discharge/getDischargedList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `doctor.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/doctorManagement/register` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/doctorScheduleManagement/register` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/doctorScheduleManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/pharmaceuticalManagement/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmaceuticalManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/pharmaceuticalManagement/update` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmaceuticalManagement/delete` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmaceuticalManagement/restore` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmaceuticalManagement/stock_query` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmaceuticalManagement/lowStock` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmaceuticalManagement/nearExpiry` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/prescriptionManagement/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/prescriptionManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/prescriptionManagement/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecord/sign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/labOrder/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/labOrder/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/attendance/checkIn` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/attendance/checkOut` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/attendance/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/slotPool/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/slotPool/adjust` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `drug_damage.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/pharmacy/drugDamage/list` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/drugDamage/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/drugDamage/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/pharmacy/drugDamage/reject` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `emergency.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/emergency/triage/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emergency/triage/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| PUT | `/api/emergency/triage/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emergency/rescue/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emergency/rescue/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/emergency/observation/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emergency/observation/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| PUT | `/api/emergency/observation/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/emergency/greenChannel/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/emergency/greenChannel/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/emergency/greenChannel/approve` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/emergency/greenChannel/close` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/emergency/medicalRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/emergency/medicalRecord/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/emergency/medicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emergency/medicalRecord/sign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `emr.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/emrTemplate/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emrTemplate/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emrTemplate/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emrTemplate/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/emrTemplate/detail` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/structuredMedicalRecord/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/structuredMedicalRecord/detail` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/sign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/progressNote/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/progressNote/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/progressNote/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/wardRound/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/wardRound/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/wardRound/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordQuality/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordQuality/check` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordQuality/summary` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `equipment.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/equipment/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/equipment/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/equipment/status` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/equipment/maintenance/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/equipment/maintenance/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/equipment/maintenance/status` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/equipment/inspection/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/equipment/inspection/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/equipment/trace/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/equipment/trace/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/equipment/inventory/check` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `exam.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/examPackage/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examPackage/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examPackage/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examPackage/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examItem/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examItem/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examItem/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examItem/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examAppointment/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examAppointment/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examAppointment/updateStatus` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examRecord/complete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examResult/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examResult/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examReport/getDetail` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `family_member.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/familyMember/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/familyMember/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| PUT | `/api/familyMember/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| DELETE | `/api/familyMember/delete` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `followup.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/followUpAppointment/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/followUp/createPlan` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/followUp/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/followUp/record` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `icd10.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/icd10/diagnosis/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/icd10/diagnosis/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| PUT | `/api/icd10/diagnosis/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/icd10/operation/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/icd10/operation/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| PUT | `/api/icd10/operation/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `imaging.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/imaging/order/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/order/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/imaging/order/status` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/order/viewer` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/imaging/report/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/report/save` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/report/submit` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/report/review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/imaging/template/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/template/save` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/imaging/viewer/{imaging_order_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/imaging/film/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/film/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/film/status` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `infection.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/infection/case/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/infection/case/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/infection/case/status` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/infection/outbreakAlert` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/infection/report` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/infection/disinfection/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/infection/disinfection/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/infection/exposure/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/infection/exposure/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infection/exposure/handle` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `infusion.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/infusion/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/infusion/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/infusion/execute` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infusion/observe` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infusion/complete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infusion/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `injection.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/injection/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/injection/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/injection/execute` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/injection/complete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/injection/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `inpatient_charge.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatientCharge/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/inpatientCharge/getDailyBill` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/inpatientCharge/settle` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/inpatientCharge/refund` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/inpatientCharge/getSummary` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/inpatientCharge/depositRecharge` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/inpatientCharge/depositBalance` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `inpatient_order.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatientOrder/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/inpatientOrder/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/audit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/stop` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/inpatientOrder/getExecutionList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/execute` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `insurance.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/insurance/catalog/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/insurance/catalog/save` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/insurance/settlement/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/insurance/settlement/create` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/integration/insurance/settlement` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/insurance/chronic/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/insurance/chronic/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/insurance/drg/group` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/insurance/drg/analysis` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/insurance/control/warnings` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `integration.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/integration/lis/result` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/integration/pacs/report` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/integration/payment/notify` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |

### `inventory_adjustment.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/pharmacy/inventoryAdjustment/list` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/inventoryAdjustment/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/inventoryAdjustment/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/pharmacy/inventoryAdjustment/reject` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `lab.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/lab/sampleReceive` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/lab/sampleReject` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/lab/sampleTracking` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/create` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/audit` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labResult/getPending` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labResult/getList` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labResult/getCritical` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/critical/notify` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/critical/acknowledge` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/labResult/critical/handle` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/labResult/detail` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |

### `lab_package.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/labPackage/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/labPackage/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| PUT | `/api/labPackage/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `lab_qc.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/labQc/list` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labQc/create` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labQc/summary` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |

### `mdt.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/mdt/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/mdt/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/mdt/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/mdt/approvalList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/mdt/approval` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `medical_record_archive.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/medicalRecordArchive/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/archive` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/medicalRecordArchive/borrow` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/return` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/seal` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `medical_record_home.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/medicalRecordHome/admissions` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordHome/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordHome/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/medicalRecordHome/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordHome/submit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `medical_record_home_quality.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/medicalRecordHomeQuality/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordHomeQuality/check` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordHomeQuality/summary` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `monitor.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/monitor/summary` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `navigation.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/navigation/nodes` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/navigation/route` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/navigation/route/departments` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| DELETE | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| DELETE | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `nursing.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/nursingAssessment/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingAssessment/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| PUT | `/api/nursingAssessment/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingAssessment/complete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/nursingPlan/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingPlan/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| PUT | `/api/nursingPlan/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/criticalCareRecord/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/criticalCareRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/surgeryNursingRecord/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/surgeryNursingRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/nursingRecord/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingRecord/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/temperatureRecord/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/temperatureRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/temperatureRecord/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `patient.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/appointmentManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/appointmentManagement/appointmentList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/appointmentManagement/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/appointmentManagement/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/registrationManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/registrationManagement/registrationList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/registrationManagement/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/registrationManagement/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/medicalRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/medicalRecord/detail` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/healthRecord/getProfile` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/healthRecord/getVisits` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/review/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `patient_card.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/patientCard/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/patientCard/issue` | ✓ | ✓ |  |  |  |  |  |  |  |  | ✓ |  |
| POST | `/api/patientCard/lost` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/patientCard/cancel` | ✓ | ✓ |  |  |  |  |  |  |  |  | ✓ |  |

### `pharmacy.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/pharmacy/batch/list` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/batch/ledger` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/dispenseList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/audit` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/dispense` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/verificationList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/pharmacy/verify` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/pharmacy/return` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/stockCheck` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/review` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/reviewList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/dispenseStats` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |

### `prescription_template.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/prescriptionTemplate/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/prescriptionTemplate/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/prescriptionTemplate/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/prescriptionTemplate/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/prescriptionTemplate/apply` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `purchase.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/purchase/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/purchase/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/purchase/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/purchase/storage` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/purchase/cancel` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `queue.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/queue/emergency` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/queue/reorder` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/queue/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/queue/progress` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/queue/callNext` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/queue/pass` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/queue/skip` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/patrol/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/patrol/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `referral.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/referral/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/referral/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/referral/updateStatus` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/referral/approvalList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/referral/approval` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `report.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/report/outpatientVolume` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/report/finance` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/report/pharmaceutical` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/report/doctorWorkload` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/report/departmentStats` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `research.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/research/export/tables` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/research/export` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/research/export/package` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/research/export/audit` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `schedule_change.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/scheduleChange/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/scheduleChange/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/scheduleChange/approve` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/scheduleChange/reject` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `scheduler.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/scheduler/status` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/scheduler/run/{job_name}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `shift_handover.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/shiftHandover/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/shiftHandover/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/shiftHandover/receive` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `skin_test.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/skinTest/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/skinTest/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/skinTest/administer` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/skinTest/assess` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/skinTest/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `special_drug.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/specialDrug/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/specialDrug/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/specialDrug/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/specialDrug/reject` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `surgery.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/surgery/perioperative/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgery/perioperative/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgery/perioperative/status` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/surgeryApplication/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgeryApplication/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgeryApplication/approve` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgeryApplication/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/surgerySchedule/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgerySchedule/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgerySchedule/start` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgerySchedule/complete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/anesthesiaRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/anesthesiaRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `system.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/log/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/log/stats` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/config/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/config/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/message/send` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/message/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/message/read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `triage.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/navigation/faq` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/navigation/faq/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/navigation/faq/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/navigation/departments` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/triage/suggest` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/triage/keywords` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |

### `triage_desk.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/triageDesk/create` | ✓ | ✓ |  |  | ✓ |  |  | ✓ |  |  |  |  |
| GET | `/api/triageDesk/getList` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  |  |
| POST | `/api/triageDesk/updateStatus` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  |  |
| POST | `/api/triageDesk/update` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  |  |

### `upload.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/upload/avatar` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/upload/report` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/uploads/avatars/{filename}` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/uploads/reports/{filename}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `user.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/test` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/publicKey` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/login` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/register` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/userInfo` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/logout` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/user/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/user/updateRole` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/user/resetPassword` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/user/delete` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/prepaid/getBalance` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/prepaid/recharge` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/prepaid/deduct` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/prepaid/refund` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/prepaid/getTransactions` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `vitalsign.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/vitalSign/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/vitalSign/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `ward.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ward/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ward/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ward/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ward/delete` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/bed/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/bed/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/bed/update` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/bed/delete` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
