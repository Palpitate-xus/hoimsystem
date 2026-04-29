# 医院信息管理系统 API 文档

baseURL：`/api`

通用响应格式：

```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

- `code` 为 200 表示成功，500 表示业务错误
- `msg` 为提示信息
- `data` 为具体返回数据（可能为空或省略）

---

## Login

| url        | method | payload | response |
|:----------:|:------:|:-------:| -------- |
| /test      | POST   | `{ data?: string }` | `{ code, msg, data }` |
| /publicKey | GET    | -       | `{ code, msg, data: { publicKey, mockServer } }` |
| /login     | POST   | `{ username, password }` | `{ code, msg, data: { accessToken } }` |
| /register  | POST   | `{ username, password, identity, address, sex, phone, birthday }` | `{ code, msg }` |
| /userInfo  | POST   | `{ accessToken }` | `{ code, msg, data: { permissions, username, avatar } }` |
| /logout    | POST   | -       | `{ code, msg }` |

### 字段说明

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

## Admin

| url                           | method | payload | response |
|:-----------------------------:|:------:| ------- |:--------:|
| /doctorManagement/getList     | GET    | -       | `{ code, msg, data: Doctor[] }` |
| /patientManagement/getList    | GET    | -       | `{ code, msg, data: Patient[] }` |
| /departmentManagement/getList | GET    | -       | `{ code, msg, data: Department[] }` |
| /departmentManagement/create  | POST   | `{ name, phone, director, location }` | `{ code, msg }` |
| /notice/getList               | GET    | -       | `{ code, msg, data: Notice[] }` |
| /notice/create                | POST   | `{ title, content, isemergency, towho, expiredtime }` | `{ code, msg }` |

### 字段说明

- `doctorManagement/getList` response `data` 数组项
  - `id`: 医生 ID
  - `name`: 姓名
  - `sex`: 性别
  - `education`: 学历
  - `phone`: 手机号
  - `permission`: 权限
  - `title`: 职称

- `patientManagement/getList` response `data` 数组项
  - `id`: 病人 ID
  - `name`: 姓名
  - `sex`: 性别（"男"/"女"）
  - `birthday`: 生日
  - `phone`: 手机号
  - `permission`: 权限
  - `address`: 地址
  - `identity`: 身份证号

- `departmentManagement/getList` response `data` 数组项
  - `id`: 科室 ID
  - `name`: 科室名称
  - `phone`: 电话
  - `location`: 位置
  - `director`: 主任姓名

- `departmentManagement/create` payload
  - `name`: 科室名称
  - `phone`: 电话
  - `director`: 主任医生 ID
  - `location`: 位置

- `notice/getList` response `data` 数组项
  - `uuid`: 通知 ID
  - `title`: 标题
  - `content`: 内容
  - `isemergency`: 是否紧急（0/1）
  - `towho`: 目标人群（如 "医生,病人"）
  - `sendtime`: 发送时间
  - `expiredtime`: 过期时间
  - `readnum`: 阅读数
  - `writer`: 发布人

- `notice/create` payload
  - `title`: 标题
  - `content`: 内容
  - `isemergency`: 是否紧急
  - `towho`: 目标人群数组（如 `["医生", "病人"]`）
  - `expiredtime`: 过期时间（字符串）

---

## Patient

| url                                      | method | payload | response |
|:----------------------------------------:|:------:|:-------:|:--------:|
| /appointmentManagement/getList           | GET    | -       | `{ code, msg, data: Appointment[] }` |
| /appointmentManagement/appointmentList   | GET    | -       | `{ code, msg, data: Schedule[] }` |
| /appointmentManagement/create            | POST   | `{ id, date, department_id, doctor_id, time, specialist }` | `{ code, msg }` |
| /appointmentManagement/cancel            | POST   | `{ uuid }` | `{ code, msg }` |
| /registrationManagement/getList          | GET    | -       | `{ code, msg, data: Registration[] }` |
| /registrationManagement/registrationList | GET    | -       | `{ code, msg, data: Schedule[] \| string }` |
| /registrationManagement/create           | POST   | `{ id, doctor_id, department_id, specialist }` | `{ code, msg }` |
| /registrationManagement/cancel           | POST   | `{ uuid }` | `{ code, msg }` |
| /chargeManagement/getList                | GET    | -       | `{ code, msg, data: Charge[] }` |
| /chargeManagement/charge                 | POST   | `{ id }` | `{ code, msg }` |

### 字段说明

- `appointmentManagement/getList` response `data` 数组项
  - `uuid`: 预约 ID
  - `doctor`: 医生姓名
  - `specialist`: 是否专家号（0/1）
  - `department`: 科室名称
  - `time`: 预约日期
  - `prefer_time`: 偏好时段
  - `appointment_time`: 预约提交时间
  - `status`: 状态（"未就诊"/"已就诊"/"已取消"）

- `appointmentManagement/appointmentList` / `registrationManagement/registrationList` response `data` 数组项
  - `id`: 排班 ID
  - `time`: 时段
  - `specialist`: 是否专家号
  - `date`: 日期（appointmentList）
  - `doctor`: 医生姓名
  - `doctor_id`: 医生 ID
  - `department_id`: 科室 ID
  - `stock`: 剩余号源
  - `status`: 挂号状态（registrationList，0=可挂，1=已挂）

- `appointmentManagement/create` payload
  - `id`: 排班 ID
  - `date`: 预约日期
  - `department_id`: 科室 ID
  - `doctor_id`: 医生 ID
  - `time`: 时段
  - `specialist`: 是否专家号

- `appointmentManagement/cancel` payload
  - `uuid`: 预约 ID

- `registrationManagement/getList` response `data` 数组项
  - `uuid`: 挂号 ID
  - `order`: 序号
  - `doctor`: 医生姓名
  - `specialist`: 是否专家号
  - `department`: 科室名称
  - `time`: 挂号时间
  - `status`: 状态（"未就诊"/"已就诊"/"已取消"）

- `registrationManagement/create` payload
  - `id`: 排班 ID
  - `doctor_id`: 医生 ID
  - `department_id`: 科室 ID
  - `specialist`: 是否专家号

- `registrationManagement/cancel` payload
  - `uuid`: 挂号 ID

- `chargeManagement/getList` response `data` 数组项
  - `id`: 收费 ID
  - `charge_time`: 收费创建时间
  - `time`: 实际缴费时间
  - `pre_id`: 处方 ID
  - `amount`: 金额
  - `status`: 状态（0=未缴费，1=已缴费）

- `chargeManagement/charge` payload
  - `id`: 收费 ID

---

## Doctor

| url                                   | method | payload | response |
|:-------------------------------------:|:------:|:-------:|:--------:|
| /doctorManagement/register            | POST   | `{ username, password, name, title, sex, phone, department, permission, education }` | `{ code, msg }` |
| /doctorScheduleManagement/register    | POST   | `{ schedule, specialist, number, doctor }` | `{ code, msg }` |
| /doctorScheduleManagement/getList     | GET    | -       | `{ code, msg, data: DoctorSchedule[] }` |
| /pharmaceuticalManagement/create      | POST   | `{ name, stock, price, expireddate, supplier, remark }` | `{ code, msg }` |
| /pharmaceuticalManagement/getList     | GET    | -       | `{ code, msg, data: Pharmaceutical[] }` |
| /pharmaceuticalManagement/stock_query | POST   | `{ id }` | `{ code, msg, data: { stock } }` |
| /prescriptionManagement/getList       | GET    | -       | `{ code, msg, data: Prescription[] }` |
| /prescriptionManagement/create        | POST   | `{ patient, phas }` | `{ code, msg }` |

### 字段说明

- `doctorManagement/register` payload
  - `username`: 登录用户名
  - `password`: 密码
  - `name`: 姓名
  - `title`: 职称
  - `sex`: 性别（"男"/"女"）
  - `phone`: 手机号
  - `department`: 科室 ID
  - `permission`: 权限（"director" 或其他）
  - `education`: 学历

- `doctorScheduleManagement/register` payload
  - `schedule`: 排班数组（如 `["星期一01", "星期二02"]`）
  - `specialist`: 是否专家号
  - `number`: 号源数量
  - `doctor`: 医生 ID

- `doctorScheduleManagement/getList` response `data` 数组项
  - `id`: 医生 ID
  - `name`: 医生姓名
  - `schedule`: 排班数组
  - `number`: 号源数
  - `specialist`: 是否专家号

- `pharmaceuticalManagement/create` payload
  - `name`: 药品名称
  - `stock`: 库存
  - `price`: 单价（字符串）
  - `expireddate`: 过期日期
  - `supplier`: 供应商
  - `remark`: 备注

- `pharmaceuticalManagement/getList` response `data` 数组项
  - `id`: 药品 ID
  - `name`: 药品名称
  - `stock`: 库存
  - `price`: 单价
  - `expireddate`: 过期日期
  - `purchasing_time`: 采购时间
  - `supplier`: 供应商
  - `remark`: 备注

- `pharmaceuticalManagement/stock_query` payload
  - `id`: 药品 ID

- `prescriptionManagement/getList` response `data` 数组项
  - `uuid`: 处方 ID
  - `doctor_id`: 医生 ID
  - `doctor_name`: 医生姓名
  - `patient_id`: 病人 ID
  - `patient_name`: 病人姓名
  - `phas`: 药品数组 `{ name, number }`

- `prescriptionManagement/create` payload
  - `patient`: 病人 ID
  - `phas`: 药品数组 `{ id: number, number: number }[]`
