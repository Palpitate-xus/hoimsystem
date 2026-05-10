# 医院门诊信息管理系统 API 文档

baseURL：`/api`

通用响应格式：

```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

- `code = 200` 表示业务成功，`code = 500` 表示业务错误
- `msg` 为提示信息
- `data` 为具体返回数据（可能为空或省略）

> **状态标识说明**：
> - ✅ **已实现** — 代码已开发完成
> - 🔧 **待实现** — 表结构已存在，接口待开发
> - 📋 **规划中** — 需求已明确，待后续迭代

---

## 一、公共模块

### 1.1 登录认证

| 状态 | url | method | payload | response |
|:----:|:----------:|:------:|:-------:| -------- |
| ✅ | /test | POST | `{ data?: string }` | `{ code, msg, data }` |
| ✅ | /publicKey | GET | - | `{ code, msg, data: { publicKey, mockServer } }` |
| ✅ | /login | POST | `{ username, password }` | `{ code, msg, data: { accessToken } }` |
| ✅ | /register | POST | `{ username, password, identity, address, sex, phone, birthday }` | `{ code, msg }` |
| ✅ | /userInfo | POST | `{ accessToken }` | `{ code, msg, data: { permissions, username, avatar } }` |
| ✅ | /logout | POST | - | `{ code, msg }` |

**字段说明：**

- `register` payload
  - `username`: 用户名
  - `password`: 密码
  - `identity`: 身份证号
  - `address`: 地址
  - `sex`: 性别（0=女，1=男）
  - `phone`: 手机号
  - `birthday`: 生日（字符串）

- `userInfo` response `data`
  - `permissions`: 权限数组，如 `["admin"]` / `["doctor"]` / `["patient"]` / `["director", "doctor"]`
  - `username`: 用户名
  - `avatar`: 头像 URL

---

## 二、管理员模块

### 2.1 医生管理

| 状态 | url | method | payload | response |
|:----:|:------------------------------:|:------:|:-------:|:--------:|
| ✅ | /doctorManagement/getList | GET | - | `{ code, msg, data: Doctor[] }` |
| ✅ | /doctorManagement/register | POST | `{ username, password, name, title, sex, phone, department, permission, education }` | `{ code, msg }` |
| ✅ | /doctorManagement/update | POST | `{ doctor_id, name, title, sex, phone, department, permission, education }` | `{ code, msg }` |
| ✅ | /doctorManagement/delete | POST | `{ doctor_id }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 医生 ID
  - `name`: 姓名
  - `sex`: 性别
  - `education`: 学历
  - `phone`: 手机号
  - `permission`: 权限
  - `title`: 职称

- `register` payload
  - `username`: 登录用户名
  - `password`: 密码
  - `name`: 姓名
  - `title`: 职称
  - `sex`: 性别（"男"/"女"）
  - `phone`: 手机号
  - `department`: 科室 ID
  - `permission`: 权限（"director" 或其他）
  - `education`: 学历

### 2.2 病人管理

| 状态 | url | method | payload | response |
|:----:|:-------------------------------:|:------:|:-------:|:--------:|
| ✅ | /patientManagement/getList | GET | - | `{ code, msg, data: Patient[] }` |
| ✅ | /patientManagement/update | POST | `{ patient_id, name, sex, phone, address }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 病人 ID
  - `name`: 姓名
  - `sex`: 性别（"男"/"女"）
  - `birthday`: 生日
  - `phone`: 手机号
  - `permission`: 权限
  - `address`: 地址
  - `identity`: 身份证号

### 2.3 科室管理

| 状态 | url | method | payload | response |
|:----:|:-------------------------------:|:------:|:-------:|:--------:|
| ✅ | /departmentManagement/getList | GET | - | `{ code, msg, data: Department[] }` |
| ✅ | /departmentManagement/create | POST | `{ name, phone, director, location }` | `{ code, msg }` |
| ✅ | /departmentManagement/update | POST | `{ department_id, name, phone, director, location }` | `{ code, msg }` |
| ✅ | /departmentManagement/delete | POST | `{ department_id }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 科室 ID
  - `name`: 科室名称
  - `phone`: 电话
  - `location`: 位置
  - `director`: 主任姓名

- `create` payload
  - `name`: 科室名称
  - `phone`: 电话
  - `director`: 主任医生 ID
  - `location`: 位置

### 2.4 通知公告管理

| 状态 | url | method | payload | response |
|:----:|:----------------------:|:------:|:-------:|:--------:|
| ✅ | /notice/getList | GET | - | `{ code, msg, data: Notice[] }` |
| ✅ | /notice/create | POST | `{ title, content, isemergency, towho, expiredtime }` | `{ code, msg }` |
| ✅ | /notice/update | POST | `{ notice_id, title, content, isemergency, towho, expiredtime }` | `{ code, msg }` |
| ✅ | /notice/delete | POST | `{ notice_id }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `uuid`: 通知 ID
  - `title`: 标题
  - `content`: 内容
  - `isemergency`: 是否紧急（0/1）
  - `towho`: 目标人群（如 "医生,病人"）
  - `sendtime`: 发送时间
  - `expiredtime`: 过期时间
  - `readnum`: 阅读数
  - `writer`: 发布人

- `create` payload
  - `title`: 标题
  - `content`: 内容
  - `isemergency`: 是否紧急
  - `towho`: 目标人群数组（如 `["医生", "病人"]`）
  - `expiredtime`: 过期时间（字符串）

### 2.5 收费记录查询

| 状态 | url | method | payload | response |
|:----:|:------------------------:|:------:|:-------:|:--------:|
| ✅ | /chargeManagement/getList | GET | - | `{ code, msg, data: Charge[] }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 收费 ID
  - `charge_time`: 收费创建时间
  - `time`: 实际缴费时间
  - `pre_id`: 处方 ID
  - `amount`: 金额
  - `status`: 状态（0=未缴费，1=已缴费）

---

## 三、病人模块

### 3.1 预约挂号

| 状态 | url | method | payload | response |
|:----:|:--------------------------------------:|:------:|:-------:|:--------:|
| ✅ | /appointmentManagement/getList | GET | - | `{ code, msg, data: Appointment[] }` |
| ✅ | /appointmentManagement/appointmentList | GET | - | `{ code, msg, data: Schedule[] }` |
| ✅ | /appointmentManagement/create | POST | `{ id, date, department_id, doctor_id, time, specialist }` | `{ code, msg }` |
| ✅ | /appointmentManagement/cancel | POST | `{ uuid }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `uuid`: 预约 ID
  - `doctor`: 医生姓名
  - `specialist`: 是否专家号（0/1）
  - `department`: 科室名称
  - `time`: 预约日期
  - `prefer_time`: 偏好时段
  - `appointment_time`: 预约提交时间
  - `status`: 状态（"未就诊"/"已就诊"/"已取消"）

- `appointmentList` response `data` 数组项
  - `id`: 排班 ID
  - `time`: 时段
  - `specialist`: 是否专家号
  - `date`: 日期
  - `doctor`: 医生姓名
  - `doctor_id`: 医生 ID
  - `department_id`: 科室 ID
  - `stock`: 剩余号源

- `create` payload
  - `id`: 排班 ID
  - `date`: 预约日期
  - `department_id`: 科室 ID
  - `doctor_id`: 医生 ID
  - `time`: 时段
  - `specialist`: 是否专家号

- `cancel` payload
  - `uuid`: 预约 ID

### 3.2 现场挂号

| 状态 | url | method | payload | response |
|:----:|:---------------------------------------:|:------:|:-------:|:--------:|
| ✅ | /registrationManagement/getList | GET | - | `{ code, msg, data: Registration[] }` |
| ✅ | /registrationManagement/registrationList | GET | - | `{ code, msg, data: Schedule[] \| string }` |
| ✅ | /registrationManagement/create | POST | `{ id, doctor_id, department_id, specialist }` | `{ code, msg }` |
| ✅ | /registrationManagement/cancel | POST | `{ uuid }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `uuid`: 挂号 ID
  - `order`: 序号
  - `doctor`: 医生姓名
  - `specialist`: 是否专家号
  - `department`: 科室名称
  - `time`: 挂号时间
  - `status`: 状态（"未就诊"/"已就诊"/"已取消"）

- `registrationList` response `data` 数组项
  - `id`: 排班 ID
  - `time`: 时段
  - `specialist`: 是否专家号
  - `doctor`: 医生姓名
  - `doctor_id`: 医生 ID
  - `department_id`: 科室 ID
  - `stock`: 剩余号源
  - `status`: 挂号状态（0=可挂，1=已挂）

- `create` payload
  - `id`: 排班 ID
  - `doctor_id`: 医生 ID
  - `department_id`: 科室 ID
  - `specialist`: 是否专家号

- `cancel` payload
  - `uuid`: 挂号 ID

### 3.3 缴费管理

| 状态 | url | method | payload | response |
|:----:|:-------------------------:|:------:|:-------:|:--------:|
| ✅ | /chargeManagement/getList | GET | - | `{ code, msg, data: Charge[] }` |
| ✅ | /chargeManagement/charge | POST | `{ id }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 收费 ID
  - `charge_time`: 收费创建时间
  - `time`: 实际缴费时间
  - `pre_id`: 处方 ID
  - `amount`: 金额
  - `status`: 状态（0=未缴费，1=已缴费）

- `charge` payload
  - `id`: 收费 ID

### 3.4 病历查询

| 状态 | url | method | payload | response |
|:----:|:------------------------------:|:------:|:-------:|:--------:|
| ✅ | /medicalRecord/getList | GET | - | `{ code, msg, data: MedicalRecord[] }` |
| ✅ | /medicalRecord/detail | POST | `{ medical_record_id }` | `{ code, msg, data: MedicalRecord }` |

**字段说明：**

- `getList` response `data` 数组项
  - `uuid`: 病历 ID
  - `consultation_time`: 就诊时间
  - `doctor_name`: 医生姓名
  - `symptom`: 症状描述
  - `result`: 诊断结果

- `detail` response `data`
  - `uuid`: 病历 ID
  - `consultation_time`: 就诊时间
  - `doctor_id`: 医生 ID
  - `doctor_name`: 医生姓名
  - `patient_id`: 病人 ID
  - `patient_name`: 病人姓名
  - `symptom`: 症状描述
  - `result`: 诊断结果

### 3.5 处方查询

| 状态 | url | method | payload | response |
|:----:|:-----------------------------:|:------:|:-------:|:--------:|
| ✅ | /prescriptionManagement/getList | GET | - | `{ code, msg, data: Prescription[] }` |

**字段说明：**

- `getList` response `data` 数组项
  - `uuid`: 处方 ID
  - `doctor_id`: 医生 ID
  - `doctor_name`: 医生姓名
  - `patient_id`: 病人 ID
  - `patient_name`: 病人姓名
  - `phas`: 药品数组 `{ name, number }`

### 3.6 检查检验结果查询

| 状态 | url | method | payload | response |
|:----:|:------------------------:|:------:|:-------:|:--------:|
| ✅ | /labResult/getList | GET | - | `{ code, msg, data: LabResult[] }` |
| ✅ | /labResult/detail | POST | `{ lab_result_id }` | `{ code, msg, data: LabResult }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 检查结果 ID
  - `check_name`: 检查名称
  - `check_time`: 检查时间
  - `result`: 结果
  - `abnormal_flag`: 是否异常（0/1）
  - `technician_name`: 技师姓名

### 3.7 健康档案

| 状态 | url | method | payload | response |
|:----:|:--------------------------:|:------:|:-------:|:--------:|
| ✅ | /healthRecord/getProfile | GET | - | `{ code, msg, data: HealthProfile }` |
| ✅ | /healthRecord/getVisits | GET | - | `{ code, msg, data: VisitRecord[] }` |

**字段说明：**

- `getProfile` response `data`
  - `patient_id`: 病人 ID
  - `name`: 姓名
  - `sex`: 性别
  - `identity`: 身份证号
  - `birthday`: 生日
  - `phone`: 手机号
  - `address`: 地址
  - `allergy_history`: 过敏史

- `getVisits` response `data` 数组项
  - `visit_time`: 就诊时间
  - `doctor_name`: 医生姓名
  - `department`: 科室
  - `diagnosis`: 诊断结果
  - `prescription_id`: 处方 ID

### 3.8 就诊评价

| 状态 | url | method | payload | response |
|:----:|:--------------------------:|:------:|:-------:|:--------:|
| ✅ | /review/create | POST | `{ doctor_id, visit_id, score, comment }` | `{ code, msg }` |

**字段说明：**

- `create` payload
  - `doctor_id`: 医生 ID
  - `visit_id`: 就诊记录 ID
  - `score`: 评分（1-5）
  - `comment`: 评价内容（可选）

---

## 四、医生模块

### 4.1 医生排班

| 状态 | url | method | payload | response |
|:----:|:-----------------------------------:|:------:|:-------:|:--------:|
| ✅ | /doctorScheduleManagement/register | POST | `{ schedule, specialist, number, doctor }` | `{ code, msg }` |
| ✅ | /doctorScheduleManagement/getList | GET | - | `{ code, msg, data: DoctorSchedule[] }` |

**字段说明：**

- `register` payload
  - `schedule`: 排班数组（如 `["星期一01", "星期二02"]`）
  - `specialist`: 是否专家号
  - `number`: 号源数量
  - `doctor`: 医生 ID

- `getList` response `data` 数组项
  - `id`: 医生 ID
  - `name`: 医生姓名
  - `schedule`: 排班数组
  - `number`: 号源数
  - `specialist`: 是否专家号

### 4.2 病历管理

| 状态 | url | method | payload | response |
|:----:|:-----------------------------:|:------:|:-------:|:--------:|
| ✅ | /medicalRecord/create | POST | `{ patient_id, symptom, result }` | `{ code, msg }` |
| ✅ | /medicalRecord/getList | GET | - | `{ code, msg, data: MedicalRecord[] }` |
| ✅ | /medicalRecord/detail | POST | `{ medical_record_id }` | `{ code, msg, data: MedicalRecord }` |
| ✅ | /medicalRecord/update | POST | `{ medical_record_id, symptom, result }` | `{ code, msg }` |

**字段说明：**

- `create` payload
  - `patient_id`: 病人 ID
  - `symptom`: 症状描述
  - `result`: 诊断结果

- `getList` response `data` 数组项
  - `uuid`: 病历 ID
  - `consultation_time`: 就诊时间
  - `patient_id`: 病人 ID
  - `patient_name`: 病人姓名
  - `symptom`: 症状描述
  - `result`: 诊断结果

- `detail` response `data`
  - `uuid`: 病历 ID
  - `consultation_time`: 就诊时间
  - `doctor_id`: 医生 ID
  - `doctor_name`: 医生姓名
  - `patient_id`: 病人 ID
  - `patient_name`: 病人姓名
  - `symptom`: 症状描述
  - `result`: 诊断结果

### 4.3 处方管理

| 状态 | url | method | payload | response |
|:----:|:---------------------------------:|:------:|:-------:|:--------:|
| ✅ | /prescriptionManagement/getList | GET | - | `{ code, msg, data: Prescription[] }` |
| ✅ | /prescriptionManagement/create | POST | `{ patient, phas }` | `{ code, msg }` |
| ✅ | /prescriptionManagement/cancel | POST | `{ prescription_id }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `uuid`: 处方 ID
  - `doctor_id`: 医生 ID
  - `doctor_name`: 医生姓名
  - `patient_id`: 病人 ID
  - `patient_name`: 病人姓名
  - `phas`: 药品数组 `{ name, number }`

- `create` payload
  - `patient`: 病人 ID
  - `phas`: 药品数组 `{ id: number, number: number }[]`

### 4.4 检查检验申请

| 状态 | url | method | payload | response |
|:----:|:------------------------:|:------:|:-------:|:--------:|
| ✅ | /labOrder/create | POST | `{ patient_id, check_type, check_items, urgent }` | `{ code, msg, data: { lab_order_id } }` |
| ✅ | /labOrder/getList | GET | - | `{ code, msg, data: LabOrder[] }` |

**字段说明：**

- `create` payload
  - `patient_id`: 病人 ID
  - `check_type`: 检查类型
  - `check_items`: 检查项目数组
  - `urgent`: 是否紧急（0/1）

- `getList` response `data` 数组项
  - `id`: 申请单 ID
  - `patient_name`: 病人姓名
  - `check_type`: 检查类型
  - `status`: 状态（0=待缴费，1=待检查，2=已完成）
  - `create_time`: 申请时间

---

## 五、药房模块

### 5.1 药品管理

| 状态 | url | method | payload | response |
|:----:|:------------------------------------:|:------:|:-------:|:--------:|
| ✅ | /pharmaceuticalManagement/getList | GET | - | `{ code, msg, data: Pharmaceutical[] }` |
| ✅ | /pharmaceuticalManagement/create | POST | `{ name, stock, price, expireddate, supplier, remark }` | `{ code, msg }` |
| ✅ | /pharmaceuticalManagement/update | POST | `{ pharmaceutical_id, name, stock, price, expireddate, supplier, remark }` | `{ code, msg }` |
| ✅ | /pharmaceuticalManagement/delete | POST | `{ pharmaceutical_id }` | `{ code, msg }` |
| ✅ | /pharmaceuticalManagement/stock_query | POST | `{ id }` | `{ code, msg, data: { stock } }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 药品 ID
  - `name`: 药品名称
  - `stock`: 库存
  - `price`: 单价
  - `expireddate`: 过期日期
  - `purchasing_time`: 采购时间
  - `supplier`: 供应商
  - `remark`: 备注

- `create` payload
  - `name`: 药品名称
  - `stock`: 库存
  - `price`: 单价（字符串）
  - `expireddate`: 过期日期
  - `supplier`: 供应商
  - `remark`: 备注

- `stock_query` payload
  - `id`: 药品 ID

### 5.2 处方审核与发药

| 状态 | url | method | payload | response |
|:----:|:-------------------------------:|:------:|:-------:|:--------:|
| ✅ | /pharmacy/dispenseList | GET | - | `{ code, msg, data: Prescription[] }` |
| ✅ | /pharmacy/audit | POST | `{ prescription_id }` | `{ code, msg }` |
| ✅ | /pharmacy/dispense | POST | `{ prescription_id }` | `{ code, msg }` |
| ✅ | /pharmacy/return | POST | `{ prescription_id, pha_id, number, reason }` | `{ code, msg }` |

**字段说明：**

- `dispenseList` response `data` 数组项
  - `uuid`: 处方 ID
  - `patient_name`: 病人姓名
  - `doctor_name`: 医生姓名
  - `phas`: 药品明细
  - `status`: 处方状态（0=待审核，1=已审核，2=已发药）

- `audit` payload
  - `prescription_id`: 处方 ID

- `dispense` payload
  - `prescription_id`: 处方 ID

- `return` payload
  - `prescription_id`: 处方 ID
  - `pha_id`: 药品 ID
  - `number`: 退药数量
  - `reason`: 退药原因

---

## 六、收费模块

### 6.1 费用查询与缴纳

| 状态 | url | method | payload | response |
|:----:|:-------------------------:|:------:|:-------:|:--------:|
| ✅ | /chargeManagement/getList | GET | - | `{ code, msg, data: Charge[] }` |
| ✅ | /chargeManagement/charge | POST | `{ id }` | `{ code, msg }` |

### 6.2 退费处理

| 状态 | url | method | payload | response |
|:----:|:--------------------------:|:------:|:-------:|:--------:|
| ✅ | /chargeManagement/refund | POST | `{ charge_id, reason }` | `{ code, msg }` |

**字段说明：**

- `refund` payload
  - `charge_id`: 收费记录 ID
  - `reason`: 退费原因

### 6.3 发票管理

| 状态 | url | method | payload | response |
|:----:|:------------------------:|:------:|:-------:|:--------:|
| ✅ | /invoice/getList | GET | - | `{ code, msg, data: Invoice[] }` |
| ✅ | /invoice/create | POST | `{ charge_id }` | `{ code, msg, data: { invoice_no } }` |
| ✅ | /invoice/print | POST | `{ invoice_id }` | `{ code, msg, data: { pdf_url } }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 发票 ID
  - `invoice_no`: 发票号码
  - `charge_id`: 收费记录 ID
  - `amount`: 金额
  - `invoice_time`: 开票时间

---

## 七、排队叫号模块

### 7.1 候诊队列

| 状态 | url | method | payload | response |
|:----:|:--------------------------:|:------:|:-------:|:--------:|
| ✅ | /queue/getList | GET | - | `{ code, msg, data: QueueItem[] }` |
| ✅ | /queue/callNext | POST | `{ doctor_id }` | `{ code, msg, data: QueueItem }` |
| ✅ | /queue/pass | POST | `{ queue_id }` | `{ code, msg }` |
| ✅ | /queue/skip | POST | `{ queue_id }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `queue_id`: 队列 ID
  - `queue_number`: 排队序号
  - `patient_name`: 病人姓名
  - `doctor_name`: 医生姓名
  - `status`: 状态（0=候诊，1=叫号中，2=已过号，3=已就诊）
  - `type`: 类型（0=现场挂号，1=预约）

- `callNext` response `data`
  - `queue_id`: 队列 ID
  - `queue_number`: 排队序号
  - `patient_name`: 病人姓名
  - `registration_uuid`: 关联挂号/预约 ID

---

## 八、报到签到模块

### 8.1 预约报到

| 状态 | url | method | payload | response |
|:----:|:----------------------:|:------:|:-------:|:--------:|
| ✅ | /checkIn/checkIn | POST | `{ appointment_uuid, identity }` | `{ code, msg, data: { queue_number } }` |

**字段说明：**

- `checkIn` payload
  - `appointment_uuid`: 预约 UUID
  - `identity`: 身份证号

- `checkIn` response `data`
  - `queue_number`: 排队序号

---

## 九、护士预检模块

### 9.1 生命体征录入

| 状态 | url | method | payload | response |
|:----:|:----------------------:|:------:|:-------:|:--------:|
| ✅ | /vitalSign/create | POST | `{ patient_id, temperature, blood_pressure_systolic, blood_pressure_diastolic, pulse, weight }` | `{ code, msg }` |
| ✅ | /vitalSign/getList | GET | - | `{ code, msg, data: VitalSign[] }` |

**字段说明：**

- `create` payload
  - `patient_id`: 病人 ID
  - `temperature`: 体温
  - `blood_pressure_systolic`: 收缩压
  - `blood_pressure_diastolic`: 舒张压
  - `pulse`: 脉搏
  - `weight`: 体重

- `getList` response `data` 数组项
  - `id`: 记录 ID
  - `patient_name`: 病人姓名
  - `temperature`: 体温
  - `blood_pressure`: 血压
  - `pulse`: 脉搏
  - `weight`: 体重
  - `check_time`: 测量时间

---

## 十、检验科模块

### 10.1 检查检验结果录入

| 状态 | url | method | payload | response |
|:----:|:-------------------------:|:------:|:-------:|:--------:|
| ✅ | /labResult/create | POST | `{ lab_order_id, sample_id, result, abnormal_flag }` | `{ code, msg }` |
| ✅ | /labResult/audit | POST | `{ lab_result_id }` | `{ code, msg }` |
| ✅ | /labResult/getPending | GET | - | `{ code, msg, data: LabOrder[] }` |

**字段说明：**

- `create` payload
  - `lab_order_id`: 检查申请单 ID
  - `sample_id`: 样本编号
  - `result`: 检查结果
  - `abnormal_flag`: 是否异常（0/1）

---

## 十一、复诊与随访模块

### 11.1 复诊预约

| 状态 | url | method | payload | response |
|:----:|:---------------------------:|:------:|:-------:|:--------:|
| ✅ | /followUpAppointment/create | POST | `{ patient_id, doctor_id, date, time }` | `{ code, msg }` |

**字段说明：**

- `create` payload
  - `patient_id`: 病人 ID
  - `doctor_id`: 医生 ID
  - `date`: 复诊日期
  - `time`: 复诊时段

### 11.2 随访管理

| 状态 | url | method | payload | response |
|:----:|:--------------------------:|:------:|:-------:|:--------:|
| ✅ | /followUp/createPlan | POST | `{ patient_id, plan_date, content }` | `{ code, msg }` |
| ✅ | /followUp/getList | GET | - | `{ code, msg, data: FollowUp[] }` |
| ✅ | /followUp/record | POST | `{ follow_up_id, result, patient_feedback }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `id`: 随访 ID
  - `patient_name`: 病人姓名
  - `plan_date`: 计划日期
  - `content`: 随访内容
  - `status`: 状态（0=待随访，1=已完成）

---

## 十二、报表统计模块

### 12.1 门诊量统计

| 状态 | url | method | payload | response |
|:----:|:------------------------:|:------:|:-------:|:--------:|
| ✅ | /report/outpatientVolume | POST | `{ start_date, end_date, group_by }` | `{ code, msg, data: ReportData }` |

**字段说明：**

- `group_by`: 分组方式（"day" / "week" / "month" / "department" / "doctor"）

- `response` `data`
  - `total_visits`: 总就诊人次
  - `details`: 分组明细数组

### 12.2 财务统计

| 状态 | url | method | payload | response |
|:----:|:----------------------:|:------:|:-------:|:--------:|
| ✅ | /report/finance | POST | `{ start_date, end_date }` | `{ code, msg, data: FinanceReport }` |

**字段说明：**

- `response` `data`
  - `total_income`: 总收入
  - `total_refund`: 总退费
  - `prescription_income`: 处方收入
  - `lab_income`: 检查收入

### 12.3 药品消耗统计

| 状态 | url | method | payload | response |
|:----:|:-------------------------:|:------:|:-------:|:--------:|
| ✅ | /report/pharmaceutical | POST | `{ start_date, end_date }` | `{ code, msg, data: PharmaReport[] }` |

### 12.4 医生工作量统计

| 状态 | url | method | payload | response |
|:----:|:----------------------:|:------:|:-------:|:--------:|
| ✅ | /report/doctorWorkload | POST | `{ start_date, end_date, doctor_id? }` | `{ code, msg, data: WorkloadReport[] }` |

**字段说明：**

- `response` `data` 数组项
  - `doctor_id`: 医生 ID
  - `doctor_name`: 医生姓名
  - `visit_count`: 接诊人数
  - `prescription_count`: 处方数
  - `lab_order_count`: 检查申请数

---

## 十三、系统管理模块

### 13.1 操作日志

| 状态 | url | method | payload | response |
|:----:|:------------------:|:------:|:-------:|:--------:|
| ✅ | /log/getList | POST | `{ user_id?, action?, start_time?, end_time?, page, page_size }` | `{ code, msg, data: { list, total } }` |

**字段说明：**

- `getList` response `data.list` 数组项
  - `log_id`: 日志 ID
  - `user_name`: 操作用户
  - `action`: 操作类型
  - `target`: 操作对象
  - `result`: 操作结果
  - `ip`: IP 地址
  - `create_time`: 操作时间

### 13.2 数据字典

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /dict/getList | POST | `{ dict_type }` | `{ code, msg, data: DictItem[] }` |
| ✅ | /dict/create | POST | `{ dict_type, dict_code, dict_value, sort_order }` | `{ code, msg }` |
| ✅ | /dict/update | POST | `{ dict_id, dict_code, dict_value, sort_order }` | `{ code, msg }` |
| ✅ | /dict/delete | POST | `{ dict_id }` | `{ code, msg }` |

### 13.3 系统参数

| 状态 | url | method | payload | response |
|:----:|:-------------------:|:------:|:-------:|:--------:|
| ✅ | /config/getList | GET | - | `{ code, msg, data: ConfigItem[] }` |
| ✅ | /config/update | POST | `{ config_key, config_value }` | `{ code, msg }` |

**字段说明：**

- `getList` response `data` 数组项
  - `config_key`: 参数键
  - `config_value`: 参数值
  - `description`: 参数说明

### 13.4 消息中心

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /message/getList | GET | - | `{ code, msg, data: Message[] }` |
| ✅ | /message/send | POST | `{ recipient_id, title, content, msg_type }` | `{ code, msg }` |
| ✅ | /message/read | POST | `{ message_id }` | `{ code, msg }` |

### 13.5 数据备份恢复

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /backup/create | POST | - | `{ code, msg, data: { filename } }` |
| ✅ | /backup/getList | GET | - | `{ code, msg, data: Backup[] }` |
| ✅ | /backup/restore | POST | `{ filename }` | `{ code, msg }` |
| ✅ | /backup/delete | POST | `{ filename }` | `{ code, msg }` |
| ✅ | /backup/download/{filename} | GET | - | file |

### 13.6 权限分配

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /user/getList | GET | `?role=` | `{ code, msg, data: User[] }` |
| ✅ | /user/updateRole | POST | `{ user_id, user_role }` | `{ code, msg }` |
| ✅ | /user/resetPassword | POST | `{ user_id }` | `{ code, msg, data: { new_password } }` |
| ✅ | /user/delete | POST | `{ user_id }` | `{ code, msg }` |

---

## 十四、新增扩展模块

### 14.1 支付接口

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /payment/create | POST | `{ charge_id, channel, amount }` | `{ code, msg, data: { payment_no, qr_code_data } }` |
| ✅ | /payment/query/{payment_no} | GET | - | `{ code, msg, data: Payment }` |
| ✅ | /payment/mockNotify | POST | `{ payment_no }` | `{ code, msg }` |
| ✅ | /payment/getList | GET | - | `{ code, msg, data: Payment[] }` |

### 14.2 智能导诊

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /triage/suggest | POST | `{ symptom }` | `{ code, msg, data: { suggestions } }` |
| ✅ | /triage/keywords | GET | - | `{ code, msg, data: string[] }` |

### 14.3 分诊台管理

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /triageDesk/create | POST | `{ identity, symptom, level, department_id, ... }` | `{ code, msg }` |
| ✅ | /triageDesk/getList | GET | `?level=&status=` | `{ code, msg, data: TriageRecord[] }` |
| ✅ | /triageDesk/updateStatus | POST | `{ triage_record_id, status }` | `{ code, msg }` |

### 14.4 耗材管理

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /consumable/getList | GET | - | `{ code, msg, data: Consumable[] }` |
| ✅ | /consumable/create | POST | `{ name, category, stock, unit, price, supplier }` | `{ code, msg }` |
| ✅ | /consumable/update | POST | `{ consumable_id, ... }` | `{ code, msg }` |
| ✅ | /consumable/delete | POST | `{ consumable_id }` | `{ code, msg }` |

### 14.5 药品采购管理

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /purchase/create | POST | `{ supplier, items[] }` | `{ code, msg, data: { order_no } }` |
| ✅ | /purchase/getList | GET | `?status=` | `{ code, msg, data: PurchaseOrder[] }` |
| ✅ | /purchase/approve | POST | `{ purchase_id }` | `{ code, msg }` |
| ✅ | /purchase/storage | POST | `{ purchase_id }` | `{ code, msg }` |
| ✅ | /purchase/cancel | POST | `{ purchase_id }` | `{ code, msg }` |

### 14.6 药品不良反应监测

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /adverseReaction/create | POST | `{ patient_id, pharmaceutical_id, symptom, severity }` | `{ code, msg }` |
| ✅ | /adverseReaction/getList | GET | - | `{ code, msg, data: AdverseReaction[] }` |
| ✅ | /adverseReaction/updateStatus | POST | `{ reaction_id, status }` | `{ code, msg }` |

### 14.7 不良事件上报

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /adverseEvent/create | POST | `{ event_type, patient_id, description, severity }` | `{ code, msg }` |
| ✅ | /adverseEvent/getList | GET | - | `{ code, msg, data: AdverseEvent[] }` |
| ✅ | /adverseEvent/updateStatus | POST | `{ event_id, status, handle_result }` | `{ code, msg }` |

### 14.8 CA数字签名

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /digitalSignature/sign | POST | `{ content }` | `{ code, msg, data: { signer, sign_time, sign_hash, cert_sn } }` |
| ✅ | /digitalSignature/verify | POST | `{ content, sign_hash }` | `{ code, msg, data: { valid } }` |

### 14.9 预交金管理

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /prepaid/getBalance | GET | `?identity=` | `{ code, msg, data: { balance } }` |
| ✅ | /prepaid/recharge | POST | `{ identity, amount }` | `{ code, msg, data: { balance } }` |
| ✅ | /prepaid/deduct | POST | `{ identity, amount }` | `{ code, msg, data: { balance } }` |

### 14.10 双向转诊

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /referral/create | POST | `{ patient_id, from_department_id, to_department_id, referral_type, reason }` | `{ code, msg }` |
| ✅ | /referral/getList | GET | - | `{ code, msg, data: Referral[] }` |
| ✅ | /referral/updateStatus | POST | `{ referral_id, status }` | `{ code, msg }` |

### 14.11 多学科会诊MDT

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /mdt/create | POST | `{ patient_id, diagnosis, department_ids }` | `{ code, msg }` |
| ✅ | /mdt/getList | GET | - | `{ code, msg, data: MdtCase[] }` |
| ✅ | /mdt/update | POST | `{ mdt_id, status, result }` | `{ code, msg }` |

### 14.12 临床路径

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /clinicalPathway/create | POST | `{ name, disease_code, disease_name, steps, expected_days }` | `{ code, msg }` |
| ✅ | /clinicalPathway/getList | GET | - | `{ code, msg, data: ClinicalPathway[] }` |
| ✅ | /clinicalPathway/update | POST | `{ pathway_id, ... }` | `{ code, msg }` |
| ✅ | /clinicalPathway/delete | POST | `{ pathway_id }` | `{ code, msg }` |

### 14.13 号源池管理

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /slotPool/getList | GET | - | `{ code, msg, data: SlotPool[] }` |
| ✅ | /slotPool/adjust | POST | `{ schedule_id, number }` | `{ code, msg }` |

### 14.14 医生考勤

| 状态 | url | method | payload | response |
|:----:|:--------------------:|:------:|:-------:|:--------:|
| ✅ | /attendance/checkIn | POST | - | `{ code, msg, data: { status } }` |
| ✅ | /attendance/checkOut | POST | - | `{ code, msg, data: { status } }` |
| ✅ | /attendance/getList | GET | `?doctor_id=&start_date=&end_date=` | `{ code, msg, data: Attendance[] }` |

---

## 十五、接口状态汇总

| 模块 | 接口总数 | ✅ 已实现 | 🔧 待实现 | 📋 规划中 |
|:----:|:--------:|:--------:|:--------:|:--------:|
| 公共模块 | 6 | 6 | 0 | 0 |
| 管理员模块 | 10 | 10 | 0 | 0 |
| 病人模块 | 17 | 17 | 0 | 0 |
| 医生模块 | 10 | 10 | 0 | 0 |
| 药房模块 | 9 | 9 | 0 | 0 |
| 收费模块 | 5 | 5 | 0 | 0 |
| 排队叫号 | 4 | 4 | 0 | 0 |
| 报到签到 | 1 | 1 | 0 | 0 |
| 护士预检 | 2 | 2 | 0 | 0 |
| 检验科 | 3 | 3 | 0 | 0 |
| 复诊随访 | 4 | 4 | 0 | 0 |
| 报表统计 | 4 | 4 | 0 | 0 |
| 系统管理 | 14 | 14 | 0 | 0 |
| 支付接口 | 4 | 4 | 0 | 0 |
| 智能导诊 | 2 | 2 | 0 | 0 |
| 分诊台 | 3 | 3 | 0 | 0 |
| 耗材管理 | 4 | 4 | 0 | 0 |
| 采购管理 | 5 | 5 | 0 | 0 |
| ADR监测 | 3 | 3 | 0 | 0 |
| 不良事件 | 3 | 3 | 0 | 0 |
| 数字签名 | 2 | 2 | 0 | 0 |
| 预交金 | 3 | 3 | 0 | 0 |
| 双向转诊 | 3 | 3 | 0 | 0 |
| MDT会诊 | 3 | 3 | 0 | 0 |
| 临床路径 | 4 | 4 | 0 | 0 |
| 号源池 | 2 | 2 | 0 | 0 |
| 医生考勤 | 3 | 3 | 0 | 0 |
| **合计** | **143** | **143** | **0** | **0** |
