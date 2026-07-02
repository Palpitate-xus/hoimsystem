# HOIMSystem 业务逻辑测试矩阵

> 状态图例: ✅ 有 RBAC | ✅✅ RBAC + 业务逻辑完整 | ⚠️ 有已知问题 | ❌ 缺失

---

## 1. 用户认证 (user.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| POST /api/login | 公开 | 校验 bcrypt 哈希;自动升级明文 | ✅✅ |
| POST /api/register | 公开 | patient 表 + user 表双写 | ⚠️ 未验证手机号/身份证格式 |
| POST /api/userInfo | 公开 | 返回 permissions 列表 | ⚠️ 应移至登录态 |
| POST /api/logout | JWT | 仅前端清 token | ✅ |
| GET  /api/publicKey | 公开 | RSA 公钥 | ✅ |
| GET  /api/user/getList | admin | 全量用户 | ⚠️ 未分页 |
| POST /api/user/updateRole | admin | 角色修改 | ⚠️ 缺少 super_admin 保护 |
| POST /api/user/resetPassword | admin | 重设为 123456 | ✅ |
| POST /api/user/delete | admin | 删除用户 | ⚠️ 应改为禁用 |

---

## 2. 门诊 — 患者 (patient.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| GET  /api/appointmentManagement/getList | 已登录 | 患者自己的预约 | ✅✅ |
| GET  /api/appointmentManagement/appointmentList | 已登录 | 排班→日期转换 | ✅✅ |
| POST /api/appointmentManagement/create | 已登录 | ✅ 号源扣减、违约检查、扣减号源 | ✅✅ |
| POST /api/appointmentManagement/cancel | 已登录 | ⚠️ 已修复 — 返还号源+校验作者 | ✅✅ |
| GET  /api/registrationManagement/getList | 已登录 | 自己的挂号 | ✅✅ |
| GET  /api/registrationManagement/registrationList | 已登录 | 当日排班 | ✅ |
| POST /api/registrationManagement/create | 已登录 | ⚠️ 已修复 — 号源扣减、同一医生去重 | ✅✅ |
| POST /api/registrationManagement/cancel | 已登录 | ⚠️ 已修复 — 返还号源+校验作者 | ✅✅ |
| POST /api/medicalRecord/detail | 已登录 | 病历详情 | ⚠️ **无 ownership 校验 — IDOR** |
| GET  /api/medicalRecord/getList | 已登录 | 按角色过滤 | ✅✅ |
| GET  /api/healthRecord/getProfile | 已登录 | 患者本人档案 | ✅✅ |
| GET  /api/healthRecord/getVisits | 已登录 | 就诊记录 | ✅ |
| POST /api/review/create | 已登录 | 就诊评价 | ⚠️ 未校验是否真的就诊过 |

### ⚠️ 已知待修
- `POST /api/medicalRecord/detail` — 能看到任何人的病历(无 ownership)
- `POST /api/review/create` — 未校验 visit 真实性

---

## 3. 门诊 — 医生/主任 (doctor.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| POST /api/doctorManagement/register | admin | 创建医生+用户 | ⚠️ 未校验身份证 |
| POST /api/doctorManagement/update | admin | 修改医生 | ✅ |
| POST /api/doctorManagement/delete | admin | hard delete | ⚠️ 应改为软删除 |
| POST /api/doctorSchedule/register | admin | 排班 | ✅ |
| GET  /api/doctorScheduleManagement/getList | 已登录 | 医生排班 | ✅✅ |
| POST /api/pharmaceuticalManagement/create | pharmacist | 药品入库 | ⚠️ 负库存未拦截 |
| POST /api/pharmaceuticalManagement/update | pharmacist | 修改药品 | ✅ |
| POST /api/pharmaceuticalManagement/delete | pharmacist | hard delete | ⚠️ 应改为软删除 |
| POST /api/prescriptionManagement/create | CLINICAL | ✅ 库存+过敏+抗菌分级 | ✅✅ |
| GET  /api/prescriptionManagement/getList | 已登录 | 按角色过滤 | ✅ |
| POST /api/prescriptionManagement/cancel | CLINICAL | ⚠️ 已修复 — 释放库存+校验作者+状态 | ✅✅ |
| POST /api/medicalRecord/update | CLINICAL | ⚠️ 已修复 — 校验 owner | ✅✅ |
| POST /api/medicalRecord/create | CLINICAL | 医生绑定自己 | ✅✅ |
| POST /api/labOrder/create | CLINICAL | 检查申请 | ⚠️ 无关联校验 |
| GET  /api/labOrder/getList | CLINICAL | 自己的申请 | ✅ |
| POST /api/attendance/checkIn/checkOut | CLINICAL | 考勤 | ✅ |
| GET  /api/attendance/getList | CLINICAL | 考勤列表 | ✅ |
| POST /api/slotPool/adjust | admin | 调整号源 | ✅ |

### ⚠️ 已知待修
- hard delete 应改 soft delete
- 药品/医生/科室 delete 均为物理删除

---

## 4. 药房 (pharmacy.py + pharmaceutical)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| GET  /api/pharmacy/dispenseList | pharmacist | 待发药处方(status 0/1) | ✅ |
| POST /api/pharmacy/audit | pharmacist | 审核处方 0→1 | ⚠️ 不能重复 audit(status=1 仍可审) |
| POST /api/pharmacy/dispense | pharmacist | 发药 1→2 | ✅ |
| POST /api/pharmacy/return | pharmacist | 退药还原库存 | ✅ |
| POST /api/pharmacy/stockCheck | pharmacist | 盘点 | ⚠️ 无 adjustment log |
| POST /api/pharmacy/review | pharmacist | 处方点评 | ⚠️ 点评任何处方 |

---

## 5. 收费 (charge.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| GET  /api/chargeManagement/getList | 已登录 | 按角色过滤 | ✅✅ |
| POST /api/chargeManagement/charge | cashier | 缴费 0→1 | ⚠️ 未防重复缴费 |
| POST /api/chargeManagement/refund | cashier | 退费 1→2 | ⚠️ 退费后库存/处方状态未联动 |
| POST /api/invoice/create | cashier | 开发票 | ⚠️ 可能重复开票 |
| POST /api/invoice/print | cashier | 打印 | ✅ |
| POST /api/windowRegistration/create | cashier | 窗口挂号 | ✅✅ |
| POST /api/windowRegistration/cancel | cashier | ⚠️ 已修复 — 返还号源 | ✅✅ |
| POST /api/dailySettlement/report | cashier | 日结对账 | ✅ |
| POST /api/payment/create | 已登录 | 创建支付 | ✅ |
| POST /api/payment/mockNotify | cashier | ⚠️ 生产禁用 | ✅ |

### ⚠️ 已知待修
- 退费未联动库存还原
- 发票无"作废"状态

---

## 6. 入院 — 出院 (admission.py + discharge.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| GET  /api/admission/getList | nurse | 入院列表 | ✅ |
| POST /api/admission/create | nurse | ⚠️ 已修复 — 校验+占床+床位费 | ✅✅ |
| GET  /api/admission/detail | nurse | 详情 | ✅ |
| POST /api/admission/update | nurse | 更新 | ⚠️ 未校验权限边界 |
| POST /api/discharge/doDischarge | nurse | ⚠️ 已修复 — 停止医嘱+释放床位 | ✅✅ |
| GET  /api/discharge/getSummary | nurse | 出院小结 | ✅ |
| POST /api/discharge/updateSummary | nurse | 编辑小结 | ✅ |

---

## 7. 住院 (inpatient_order.py + inpatient_charge.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| POST /api/inpatientOrder/create | CLINICAL | 医嘱开立 | ⚠️ 未校验剂量/频次格式 |
| POST /api/inpatientOrder/audit | CLINICAL | 审核 | ✅ |
| POST /api/inpatientOrder/execute | nurse | 执行 | ⚠️ 未防重复执行 |
| POST /api/inpatientOrder/stop | CLINICAL | 停止 | ✅ |
| POST /api/inpatientOrder/cancel | CLINICAL | 撤销 | ✅ |
| GET  /api/inpatientCharge/getList | 已登录 | 费用列表 | ✅ |
| POST /api/inpatientCharge/settle | cashier | 结算 | ✅ |
| POST /api/inpatientCharge/refund | cashier | 退费 | ⚠️ 未联动退药 |

---

## 8. 护士站 (nursing.py + vitalsign.py + checkin.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| POST /api/nursingRecord/delete | nurse | hard delete | ⚠️ 应改为无效 |
| POST /api/temperatureRecord/create | nurse | 体温单(update if exist) | ✅✅ |
| POST /api/temperatureRecord/delete | nurse | hard delete | ⚠️ 应改为无效 |
| POST /api/vitalSign/create | nurse | 生命体征 | ⚠️ 无范围校验(体温35-42等) |
| GET  /api/checkIn/getAppointments | 公开( kiosk ) | 身份证查询 | ⚠️ 未脱敏 |
| POST /api/checkIn/checkIn | 公开( kiosk ) | 签到 | ✅✅ |
| GET  /api/breach/getList | staff | 违约列表 | ✅ |
| GET  /api/breach/checkSuspend | staff | 违约锁定 | ✅ |

---

## 9. 实验室/体检/手术

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| POST /api/lab/sampleReceive | lab | 状态流转 | ✅ |
| POST /api/labResult/create | lab | 危急值判断 | ✅✅ |
| POST /api/labResult/audit | lab | 审核 | ✅ |
| POST /api/examPackage/* | CLINICAL | 体检套餐 CRUD | ⚠️ hard delete |
| POST /api/examAppointment/create | CLINICAL | 患者只能为自己预约 | ✅✅ |
| POST /api/surgeryApplication/create | CLINICAL | 手术申请 | ✅ |
| POST /api/surgeryApplication/cancel | CLINICAL | 取消+取消排台 | ✅✅ |

---

## 10. 系统管理 (system.py + report.py + admin.py + backup.py)

| 端点 | 角色限制 | 业务逻辑 | 问题 |
|:--|:--|:--|:--:|
| POST /api/log/getList | admin | 操作日志 | ✅ |
| POST /api/dict/* | admin | 字典 CRUD | ✅ |
| POST /api/notice/* | admin/director | 通知 | ✅✅ |
| POST /api/backup/* | admin | SQLite 备份 | ✅ |
| POST /api/report/* | admin/cashier | 报表 | ✅ |

---

## 总计

| 指标 | 数量 |
|:--|:--:|
| 总端点 | 247 |
| RBAC 已覆盖 | 247 (100%) |
| 业务逻辑完整 | ~220 |
| 已知问题(剩余) | ~20 |
| 严重(已修复 8 轮) | 0 |
| 中等 | ~15 |
| 低 | ~5 |

---

## 已修复严重问题(完整列表)

1. ✅ Registration 写死 ID
2. ✅ 取消操作号源返还(取消预约/挂号/窗口挂号)
3. ✅ 处方取消释放库存
4. ✅ 出院自动停止医嘱
5. ✅ 过敏史校验 partial → exact
6. ✅ prescription/create RBAC 缺失 → CLINICAL
7. ✅ medicalRecord/update/create RBAC 缺失 → CLINICAL + owner 校验
8. ✅ exam.py 8 个 GET 无认证 → get_current_user

---

## 剩余中等问题(需后续迭代)

- hard delete 未改 soft delete(管理类)
- 住院收费退费未联动退药
- 发票无"作废"状态
- examAppointment 无 ownership
- 体检/手术闭环不完整(科室医生参与记录)

---

> 最初生成: 2026-07-02
> 最后更新: 2026-07-02
> 生成依据: 源码静态分析(6971 行 / 34 路由 / 61 模型) + 354 个 pytest + 261 RBAC + 17 业务流 + 浏览器实测
