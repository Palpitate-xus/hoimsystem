# HIS-OP 后端 API 测试报告

> **生成时间**：2026-05-18 02:31:15
> **测试环境**：http://localhost:8000
> **测试账号**：admin
> **测试脚本**：[tests/api/test_all_endpoints.py](../tests/api/test_all_endpoints.py)

---

## 一、测试总览

- **测试用例总数**：188
- **通过**：180 (95.7%)
- **失败**：8 (4.3%)
- **覆盖模块**：74
- **接口端点**：248（OpenAPI 统计）

### 分模块统计

| 模块 | 用例数 | 通过 | 失败 | 通过率 |
|:----|:----:|:----:|:----:|:----:|
| ✅ admission | 5 | 5 | 0 | 100% |
| ✅ adverseEvent | 2 | 2 | 0 | 100% |
| ✅ adverseReaction | 2 | 2 | 0 | 100% |
| ✅ anesthesiaRecord | 1 | 1 | 0 | 100% |
| ⚠️ appointmentManagement | 5 | 3 | 2 | 60% |
| ✅ attendance | 3 | 3 | 0 | 100% |
| ✅ backup | 4 | 4 | 0 | 100% |
| ✅ bed | 2 | 2 | 0 | 100% |
| ✅ breach | 2 | 2 | 0 | 100% |
| ✅ chargeManagement | 3 | 3 | 0 | 100% |
| ✅ checkIn | 2 | 2 | 0 | 100% |
| ✅ clinicalPathway | 2 | 2 | 0 | 100% |
| ✅ config | 2 | 2 | 0 | 100% |
| ✅ consumable | 3 | 3 | 0 | 100% |
| ✅ dailySettlement | 1 | 1 | 0 | 100% |
| ✅ departmentManagement | 4 | 4 | 0 | 100% |
| ✅ dict | 3 | 3 | 0 | 100% |
| ✅ digitalSignature | 2 | 2 | 0 | 100% |
| ✅ discharge | 3 | 3 | 0 | 100% |
| ✅ doctorManagement | 5 | 5 | 0 | 100% |
| ✅ doctorScheduleManagement | 2 | 2 | 0 | 100% |
| ✅ emrTemplate | 1 | 1 | 0 | 100% |
| ✅ examAppointment | 1 | 1 | 0 | 100% |
| ✅ examItem | 1 | 1 | 0 | 100% |
| ✅ examPackage | 1 | 1 | 0 | 100% |
| ✅ examRecord | 1 | 1 | 0 | 100% |
| ✅ examReport | 1 | 1 | 0 | 100% |
| ✅ examResult | 1 | 1 | 0 | 100% |
| ✅ followUp | 3 | 3 | 0 | 100% |
| ✅ followUpAppointment | 1 | 1 | 0 | 100% |
| ✅ healthRecord | 2 | 2 | 0 | 100% |
| ✅ inpatientCharge | 3 | 3 | 0 | 100% |
| ✅ inpatientOrder | 3 | 3 | 0 | 100% |
| ✅ invoice | 2 | 2 | 0 | 100% |
| ✅ lab | 1 | 1 | 0 | 100% |
| ❌ labOrder | 2 | 1 | 1 | 50% |
| ✅ labResult | 2 | 2 | 0 | 100% |
| ✅ log | 1 | 1 | 0 | 100% |
| ✅ login | 5 | 5 | 0 | 100% |
| ✅ logout | 1 | 1 | 0 | 100% |
| ✅ mdt | 2 | 2 | 0 | 100% |
| ⚠️ medicalRecord | 5 | 4 | 1 | 80% |
| ✅ medicalRecordQuality | 2 | 2 | 0 | 100% |
| ✅ message | 3 | 3 | 0 | 100% |
| ✅ notice | 4 | 4 | 0 | 100% |
| ❌ nursingRecord | 1 | 0 | 1 | 0% |
| ✅ patientManagement | 6 | 6 | 0 | 100% |
| ✅ patrol | 1 | 1 | 0 | 100% |
| ✅ payment | 3 | 3 | 0 | 100% |
| ✅ pharmaceuticalManagement | 9 | 9 | 0 | 100% |
| ✅ pharmacy | 6 | 6 | 0 | 100% |
| ✅ prepaid | 4 | 4 | 0 | 100% |
| ⚠️ prescriptionManagement | 3 | 2 | 1 | 67% |
| ✅ progressNote | 1 | 1 | 0 | 100% |
| ✅ publicKey | 1 | 1 | 0 | 100% |
| ✅ purchase | 3 | 3 | 0 | 100% |
| ✅ queue | 3 | 3 | 0 | 100% |
| ✅ referral | 2 | 2 | 0 | 100% |
| ⚠️ register | 3 | 2 | 1 | 67% |
| ✅ registrationManagement | 4 | 4 | 0 | 100% |
| ✅ report | 4 | 4 | 0 | 100% |
| ✅ slotPool | 2 | 2 | 0 | 100% |
| ✅ structuredMedicalRecord | 1 | 1 | 0 | 100% |
| ✅ surgeryApplication | 1 | 1 | 0 | 100% |
| ✅ surgerySchedule | 1 | 1 | 0 | 100% |
| ❌ temperatureRecord | 1 | 0 | 1 | 0% |
| ✅ triage | 3 | 3 | 0 | 100% |
| ✅ triageDesk | 2 | 2 | 0 | 100% |
| ✅ user | 7 | 7 | 0 | 100% |
| ✅ userInfo | 2 | 2 | 0 | 100% |
| ✅ vitalSign | 3 | 3 | 0 | 100% |
| ✅ ward | 2 | 2 | 0 | 100% |
| ✅ wardRound | 1 | 1 | 0 | 100% |
| ✅ windowRegistration | 1 | 1 | 0 | 100% |

### 业务码约定

| 业务码 | 含义 | 何时出现 |
|:----:|:----|:----|
| 200 | 成功 | 正常调用，含返回数据 |
| 401 | 未授权 | 部分敏感接口未携带有效 token |
| 500 | 业务失败 | 资源不存在、参数不合法、业务规则不满足 |
| 422 | 参数校验失败 | Pydantic 校验失败，body 中给出 detail |

> ⚠️ 注意：本系统未严格遵循 RESTful HTTP 状态码约定，大量"未找到"等业务错误以 HTTP 200 + biz=500 的形式返回，而不是 HTTP 404。这是历史设计选择。

---

## 二、详细测试用例与结果

### admission（5/5 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/admission/getList` | 入院记录 | 默认查询 | 200 | 200 | biz=200 | 36ms | ✅ |
| GET | `/api/admission/getInpatientList` | 在院患者 | 默认查询 | 200 | 200 | biz=200 | 25ms | ✅ |
| GET | `/api/admission/getAvailableBeds` | 可用床位 | 按病区查询 | 200 | 200 | biz=200 | 18ms | ✅ |
| GET | `/api/admission/detail` | 入院详情-存在 | 查看已有入院 | 200 | 200 | biz=200 | 7ms | ✅ |
| GET | `/api/admission/detail` | 入院详情-不存在 | admission_id不存在 | 200 | 500 | biz=500 | 4ms | ✅ |

### adverseEvent（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/adverseEvent/getList` | 不良事件列表 | 默认查询 | 200 | 200 | biz=200 | 12ms | ✅ |
| POST | `/api/adverseEvent/create` | 上报不良事件 | 新增事件 | 200 | 200 | biz=200 | 17ms | ✅ |

### adverseReaction（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/adverseReaction/getList` | ADR列表 | 默认查询 | 200 | 200 | biz=200 | 18ms | ✅ |
| POST | `/api/adverseReaction/create` | 上报ADR | 新增不良反应 | 200 | 200 | biz=200 | 17ms | ✅ |

### anesthesiaRecord（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/anesthesiaRecord/getList` | 麻醉记录 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |

### appointmentManagement（3/5 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/appointmentManagement/getList` | 预约列表(管理) | 管理员查看 | 200 | 200 | biz=200 | 7ms | ✅ |
| GET | `/api/appointmentManagement/appointmentList` | 我的预约 | 默认查询 | 500 | None | biz=200 | 20ms | ❌ |
| POST | `/api/appointmentManagement/create` | 创建预约 | admin非患者返回500 | 0 | None | biz=500 | 10ms | ❌ |
| POST | `/api/appointmentManagement/create` | 创建预约-缺字段 | 缺少必填字段 | 422 | None | http=422 | 14ms | ✅ |
| POST | `/api/appointmentManagement/cancel` | 取消预约-不存在 | 系统不报错返回200 | 200 | 200 | biz=200 | 11ms | ✅ |

### attendance（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/attendance/getList` | 考勤列表 | 默认查询 | 200 | 200 | biz=200 | 7ms | ✅ |
| POST | `/api/attendance/checkIn` | 签到 | admin非医生返回500 | 200 | 500 | biz=500 | 13ms | ✅ |
| POST | `/api/attendance/checkOut` | 签退 | admin非医生返回500 | 200 | 500 | biz=500 | 12ms | ✅ |

### backup（4/4 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/backup/getList` | 备份列表 | 默认查询 | 200 | 200 | biz=200 | 7ms | ✅ |
| POST | `/api/backup/create` | 创建备份 | 执行备份 | 200 | 200 | biz=200 | 13ms | ✅ |
| POST | `/api/backup/delete` | 删除备份-不存在 | filename不存在 | 200 | 500 | biz=500 | 13ms | ✅ |
| POST | `/api/backup/restore` | 还原-不存在 | filename不存在 | 200 | 500 | biz=500 | 12ms | ✅ |

### bed（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/bed/getList` | 床位列表 | 默认查询 | 200 | 200 | biz=200 | 63ms | ✅ |
| POST | `/api/bed/create` | 新增床位 | 正常新增 | 200 | 200 | biz=200 | 13ms | ✅ |

### breach（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/breach/getList` | 违约记录 | 默认查询 | 200 | 200 | biz=200 | 7ms | ✅ |
| GET | `/api/breach/checkSuspend` | 暂停状态 | 按patient_id查询 | 200 | 200 | biz=200 | 7ms | ✅ |

### chargeManagement（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/chargeManagement/getList` | 收费列表 | 默认查询 | 200 | 200 | biz=200 | 56ms | ✅ |
| POST | `/api/chargeManagement/charge` | 缴费-不存在 | 系统不报错返回200 | 200 | 200 | biz=200 | 10ms | ✅ |
| POST | `/api/chargeManagement/refund` | 退费-不存在 | charge_id不存在 | 200 | 500 | biz=500 | 11ms | ✅ |

### checkIn（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/checkIn/getAppointments` | 可签到预约 | 按身份证号查询 | 200 | 200 | biz=200 | 8ms | ✅ |
| POST | `/api/checkIn/checkIn` | 签到-不存在 | appointment_uuid不存在 | 200 | 500 | biz=500 | 12ms | ✅ |

### clinicalPathway（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/clinicalPathway/getList` | 临床路径列表 | 默认查询 | 200 | 200 | biz=200 | 8ms | ✅ |
| POST | `/api/clinicalPathway/create` | 新增临床路径 | 正常新增 | 200 | 200 | biz=200 | 15ms | ✅ |

### config（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/config/getList` | 配置列表 | 默认查询 | 200 | 200 | biz=200 | 4ms | ✅ |
| POST | `/api/config/update` | 更新配置 | 配置表为空返回500 | 200 | 500 | biz=500 | 11ms | ✅ |

### consumable（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/consumable/getList` | 耗材列表 | 默认查询 | 200 | 200 | biz=200 | 9ms | ✅ |
| POST | `/api/consumable/create` | 新增耗材 | 正常新增 | 200 | 200 | biz=200 | 15ms | ✅ |
| POST | `/api/consumable/delete` | 删除耗材-不存在 | consumable_id不存在 | 200 | 500 | biz=500 | 12ms | ✅ |

### dailySettlement（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/dailySettlement/report` | 日结 | 按日期结算 | 200 | 200 | biz=200 | 11ms | ✅ |

### departmentManagement（4/4 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/departmentManagement/getList` | 科室列表 | 默认查询 | 200 | 200 | biz=200 | 20ms | ✅ |
| POST | `/api/departmentManagement/create` | 新增科室 | 创建测试科室 | 200 | 200 | biz=200 | 13ms | ✅ |
| POST | `/api/departmentManagement/update` | 更新科室 | 更新已有科室 | 200 | 200 | biz=200 | 10ms | ✅ |
| POST | `/api/departmentManagement/delete` | 删除科室-不存在 | department_id不存在 | 200 | 500 | biz=500 | 9ms | ✅ |

### dict（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/dict/getList` | 字典列表 | 按类型查询 | 200 | 200 | biz=200 | 6ms | ✅ |
| POST | `/api/dict/create` | 新增字典 | 创建字典项 | 200 | 200 | biz=200 | 13ms | ✅ |
| POST | `/api/dict/delete` | 删除字典-不存在 | dict_id不存在 | 200 | 500 | biz=500 | 11ms | ✅ |

### digitalSignature（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/digitalSignature/sign` | 数字签名 | 对内容签名 | 200 | 200 | biz=200 | 15ms | ✅ |
| POST | `/api/digitalSignature/verify` | 验签-无效 | 签名错误 | 200 | 200 | biz=200 | 10ms | ✅ |

### discharge（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/discharge/getDischargedList` | 出院列表 | 默认查询 | 200 | 200 | biz=200 | 22ms | ✅ |
| POST | `/api/discharge/doDischarge` | 办理出院-不存在 | admission_id不存在 | 200 | 500 | biz=500 | 11ms | ✅ |
| GET | `/api/discharge/getSummary` | 出院摘要-不存在 | admission_id不存在 | 200 | 500 | biz=500 | 5ms | ✅ |

### doctorManagement（5/5 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/doctorManagement/getList` | 医生列表 | 默认查询 | 200 | 200 | biz=200 | 8ms | ✅ |
| GET | `/api/doctorManagement/getList` | 医生列表-按科室 | 按科室过滤 | 200 | 200 | biz=200 | 9ms | ✅ |
| POST | `/api/doctorManagement/register` | 新增医生 | 管理员新增 | 200 | 200 | biz=200 | 351ms | ✅ |
| POST | `/api/doctorManagement/update` | 更新医生 | 修改医生信息 | 200 | 200 | biz=200 | 10ms | ✅ |
| POST | `/api/doctorManagement/delete` | 删除医生-不存在 | doctor_id不存在 | 200 | 500 | biz=500 | 10ms | ✅ |

### doctorScheduleManagement（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/doctorScheduleManagement/getList` | 医生排班 | 按医生查询 | 200 | 200 | biz=200 | 18ms | ✅ |
| POST | `/api/doctorScheduleManagement/register` | 新增排班 | 创建排班 | 200 | 200 | biz=200 | 11ms | ✅ |

### emrTemplate（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/emrTemplate/getList` | 病历模板 | 默认查询 | 200 | 200 | biz=200 | 16ms | ✅ |

### examAppointment（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/examAppointment/getList` | 体检预约 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |

### examItem（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/examItem/getList` | 体检项目 | 默认查询 | 200 | 200 | biz=200 | 9ms | ✅ |

### examPackage（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/examPackage/getList` | 体检套餐 | 默认查询 | 200 | 200 | biz=200 | 7ms | ✅ |

### examRecord（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/examRecord/getList` | 体检记录 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |

### examReport（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/examReport/getDetail` | 体检报告-不存在 | record_id不存在 | 200 | 500 | biz=500 | 6ms | ✅ |

### examResult（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/examResult/getList` | 体检结果 | 按record_id查询 | 200 | 200 | biz=200 | 6ms | ✅ |

### followUp（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/followUp/getList` | 随访列表 | 默认查询 | 200 | 200 | biz=200 | 11ms | ✅ |
| POST | `/api/followUp/createPlan` | 创建随访 | 医生创建随访 | 200 | 200 | biz=200 | 18ms | ✅ |
| POST | `/api/followUp/record` | 随访记录-不存在 | follow_up_id不存在 | 200 | 500 | biz=500 | 12ms | ✅ |

### followUpAppointment（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/followUpAppointment/create` | 随访预约 | 创建预约 | 200 | 200 | biz=200 | 17ms | ✅ |

### healthRecord（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/healthRecord/getProfile` | 健康档案 | admin访问返回500（需患者登录） | 200 | 500 | biz=500 | 8ms | ✅ |
| GET | `/api/healthRecord/getVisits` | 就诊记录 | 按patient_id查询 | 200 | 200 | biz=200 | 8ms | ✅ |

### inpatientCharge（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/inpatientCharge/getList` | 住院费用列表 | 默认查询 | 200 | 200 | biz=200 | 22ms | ✅ |
| GET | `/api/inpatientCharge/getDailyBill` | 每日清单 | 查看已有入院 | 200 | 200 | biz=200 | 7ms | ✅ |
| GET | `/api/inpatientCharge/getSummary` | 费用汇总 | 查看已有入院 | 200 | 200 | biz=200 | 6ms | ✅ |

### inpatientOrder（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/inpatientOrder/getList` | 住院医嘱列表 | 默认查询 | 200 | 200 | biz=200 | 26ms | ✅ |
| POST | `/api/inpatientOrder/audit` | 审核医嘱-不存在 | order_id不存在 | 200 | 500 | biz=500 | 13ms | ✅ |
| GET | `/api/inpatientOrder/getExecutionList` | 医嘱执行列表 | 默认查询 | 200 | 200 | biz=200 | 64ms | ✅ |

### invoice（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/invoice/getList` | 发票列表 | 默认查询 | 200 | 200 | biz=200 | 19ms | ✅ |
| POST | `/api/invoice/create` | 创建发票-缺字段 | 缺少必填字段 | 422 | None | http=422 | 10ms | ✅ |

### lab（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/lab/sampleTracking` | 样本追踪 | lab_order_id不存在 | 200 | 500 | biz=500 | 6ms | ✅ |

### labOrder（1/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/labOrder/getList` | 检验申请列表 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |
| POST | `/api/labOrder/create` | 创建检验申请 | 医生开检查单 | 200 | 500 | biz=200 | 13ms | ❌ |

### labResult（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/labResult/getPending` | 待录入结果 | 默认查询 | 200 | 200 | biz=200 | 20ms | ✅ |
| GET | `/api/labResult/getList` | 结果列表 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |

### log（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/log/getList` | 操作日志 | 查询日志列表 | 200 | 200 | biz=200 | 8ms | ✅ |

### login（5/5 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/login` | 正常登录 | admin账号登录 | 200 | 200 | biz=200 | 317ms | ✅ |
| POST | `/api/login` | 错误密码 | 密码错误 | 200 | 500 | biz=500 | 319ms | ✅ |
| POST | `/api/login` | 不存在用户 | 用户名不存在 | 200 | 500 | biz=500 | 10ms | ✅ |
| POST | `/api/login` | 缺少密码字段 | 缺少必填字段 | 422 | None | http=422 | 7ms | ✅ |
| POST | `/api/login` | 无token访问登录 | 登录不需要token | 200 | 200 | biz=200 | 421ms | ✅ |

### logout（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/logout` | 登出 | 退出登录 | 200 | 200 | biz=200 | 6ms | ✅ |

### mdt（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/mdt/getList` | MDT列表 | 默认查询 | 200 | 200 | biz=200 | 17ms | ✅ |
| POST | `/api/mdt/create` | 创建MDT | 多学科会诊 | 200 | 200 | biz=200 | 15ms | ✅ |

### medicalRecord（4/5 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/medicalRecord/getList` | 病历列表 | 默认查询 | 200 | 200 | biz=200 | 3ms | ✅ |
| POST | `/api/medicalRecord/create` | 创建病历 | 医生写病历 | 200 | 500 | biz=200 | 10ms | ❌ |
| POST | `/api/medicalRecord/update` | 更新病历 | 修改病历内容 | 200 | 200 | biz=200 | 13ms | ✅ |
| POST | `/api/medicalRecord/detail` | 病历详情 | 查看已存在病历 | 200 | 200 | biz=200 | 13ms | ✅ |
| POST | `/api/medicalRecord/detail` | 病历详情-不存在 | medical_record_id不存在 | 200 | 500 | biz=500 | 9ms | ✅ |

### medicalRecordQuality（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/medicalRecordQuality/getList` | 质控列表 | 默认查询 | 200 | 200 | biz=200 | 5ms | ✅ |
| GET | `/api/medicalRecordQuality/summary` | 质控统计 | 默认查询 | 200 | 200 | biz=200 | 7ms | ✅ |

### message（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/message/getList` | 消息列表 | 查询消息 | 200 | 200 | biz=200 | 8ms | ✅ |
| POST | `/api/message/send` | 发送消息 | 给用户发站内信 | 200 | 200 | biz=200 | 15ms | ✅ |
| POST | `/api/message/read` | 标记已读-不存在 | 系统不报错返回200 | 200 | 200 | biz=200 | 12ms | ✅ |

### notice（4/4 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/notice/getList` | 公告列表 | 默认查询 | 200 | 200 | biz=200 | 11ms | ✅ |
| POST | `/api/notice/create` | 新增公告 | 管理员发公告 | 200 | 200 | biz=200 | 17ms | ✅ |
| POST | `/api/notice/delete` | 删除公告-不存在 | notice_id不存在 | 200 | 500 | biz=500 | 11ms | ✅ |
| POST | `/api/notice/create` | 未授权-发公告 | 无token发公告 | 401 | None | http=401 | 9ms | ✅ |

### nursingRecord（0/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/nursingRecord/getList` | 护理记录 | 默认查询 | 500 | None | biz=200 | 7ms | ❌ |

### patientManagement（6/6 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/patientManagement/getList` | 患者列表-默认 | 默认查询 | 200 | 200 | biz=200 | 10ms | ✅ |
| GET | `/api/patientManagement/getList` | 患者列表-分页 | page=1&page_size=10 | 200 | 200 | biz=200 | 6ms | ✅ |
| GET | `/api/patientManagement/getList` | 患者列表-关键字 | 按姓名模糊搜索 | 200 | 200 | biz=200 | 6ms | ✅ |
| POST | `/api/patientManagement/update` | 更新患者 | 更新已存在患者 | 200 | 200 | biz=200 | 12ms | ✅ |
| POST | `/api/patientManagement/update` | 更新患者-不存在 | patient_id不存在 | 200 | 500 | biz=500 | 11ms | ✅ |
| POST | `/api/patientManagement/update` | 更新患者-缺字段 | 缺少必填字段 | 422 | None | http=422 | 10ms | ✅ |

### patrol（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/patrol/getList` | 巡视记录 | 默认查询 | 200 | 200 | biz=200 | 17ms | ✅ |

### payment（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/payment/getList` | 支付记录 | 默认查询 | 200 | 200 | biz=200 | 7ms | ✅ |
| POST | `/api/payment/create` | 创建支付-不存在 | charge_id不存在 | 200 | 500 | biz=500 | 12ms | ✅ |
| GET | `/api/payment/query/test_pay_xxx` | 查询支付-不存在 | payment_no不存在 | 200 | 500 | biz=500 | 5ms | ✅ |

### pharmaceuticalManagement（9/9 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/pharmaceuticalManagement/getList` | 药品列表 | 默认查询 | 200 | 200 | biz=200 | 10ms | ✅ |
| GET | `/api/pharmaceuticalManagement/getList` | 药品-按名称 | 按名称搜索 | 200 | 200 | biz=200 | 8ms | ✅ |
| POST | `/api/pharmaceuticalManagement/create` | 新增药品 | 正常新增 | 200 | 200 | biz=200 | 15ms | ✅ |
| POST | `/api/pharmaceuticalManagement/create` | 新增药品-负库存 | 负数校验 | 422 | None | http=422 | 10ms | ✅ |
| POST | `/api/pharmaceuticalManagement/update` | 更新药品 | 修改库存 | 200 | 200 | biz=200 | 11ms | ✅ |
| POST | `/api/pharmaceuticalManagement/stock_query` | 查库存 | 按id查询 | 200 | 200 | biz=200 | 12ms | ✅ |
| GET | `/api/pharmaceuticalManagement/lowStock` | 低库存 | 默认阈值 | 200 | 200 | biz=200 | 6ms | ✅ |
| GET | `/api/pharmaceuticalManagement/nearExpiry` | 近效期 | 默认30天 | 200 | 200 | biz=200 | 6ms | ✅ |
| POST | `/api/pharmaceuticalManagement/delete` | 删除药品-不存在 | pharmaceutical_id不存在 | 200 | 500 | biz=500 | 12ms | ✅ |

### pharmacy（6/6 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/pharmacy/dispenseList` | 待发药列表 | 默认查询 | 200 | 200 | biz=200 | 40ms | ✅ |
| GET | `/api/pharmacy/reviewList` | 处方点评列表 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |
| POST | `/api/pharmacy/audit` | 审核处方-不存在 | prescription_id不存在 | 200 | 500 | biz=500 | 10ms | ✅ |
| POST | `/api/pharmacy/dispense` | 发药-不存在 | prescription_id不存在 | 200 | 500 | biz=500 | 12ms | ✅ |
| POST | `/api/pharmacy/stockCheck` | 库存盘点 | 正常盘点 | 200 | 200 | biz=200 | 11ms | ✅ |
| POST | `/api/pharmacy/review` | 处方点评 | 对处方评分 | 200 | 200 | biz=200 | 15ms | ✅ |

### prepaid（4/4 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/prepaid/getBalance` | 查余额 | 按身份证号查询 | 200 | 200 | biz=200 | 6ms | ✅ |
| POST | `/api/prepaid/recharge` | 充值500 | 正常充值 | 200 | 200 | biz=200 | 18ms | ✅ |
| POST | `/api/prepaid/recharge` | 充值负数 | 负数金额应失败 | 200 | 500 | biz=500 | 12ms | ✅ |
| POST | `/api/prepaid/deduct` | 扣费 | 正常扣费 | 200 | 200 | biz=200 | 18ms | ✅ |

### prescriptionManagement（2/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/prescriptionManagement/getList` | 处方列表 | 默认查询 | 200 | 200 | biz=200 | 62ms | ✅ |
| POST | `/api/prescriptionManagement/create` | 创建处方 | 医生开处方 | 200 | 500 | biz=200 | 11ms | ❌ |
| POST | `/api/prescriptionManagement/cancel` | 取消处方-不存在 | prescription_id不存在 | 200 | 500 | biz=500 | 9ms | ✅ |

### progressNote（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/progressNote/getList` | 病程记录 | 按admission_id查询 | 200 | 200 | biz=200 | 5ms | ✅ |

### publicKey（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/publicKey` | 获取公钥 | RSA公钥 | 200 | 200 | biz=200 | 3ms | ✅ |

### purchase（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/purchase/getList` | 采购单列表 | 默认查询 | 200 | 200 | biz=200 | 16ms | ✅ |
| POST | `/api/purchase/create` | 创建采购单 | 正常新增 | 200 | 200 | biz=200 | 18ms | ✅ |
| POST | `/api/purchase/approve` | 审批-不存在 | purchase_id不存在 | 200 | 500 | biz=500 | 10ms | ✅ |

### queue（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/queue/getList` | 排队列表 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |
| POST | `/api/queue/callNext` | 叫号-空队列 | doctor_id不存在 | 200 | 500 | biz=500 | 12ms | ✅ |
| POST | `/api/queue/emergency` | 标记急诊-不存在 | queue_id不存在 | 200 | 500 | biz=500 | 12ms | ✅ |

### referral（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/referral/getList` | 转诊列表 | 默认查询 | 200 | 200 | biz=200 | 22ms | ✅ |
| POST | `/api/referral/create` | 发起转诊 | 门诊转诊 | 200 | 200 | biz=200 | 15ms | ✅ |

### register（2/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/register` | 正常注册 | 新患者注册 | 200 | 500 | biz=200 | 6ms | ❌ |
| POST | `/api/register` | 重复用户名 | 用户名已存在 | 200 | 500 | biz=500 | 5ms | ✅ |
| POST | `/api/register` | 无效手机号 | 手机号格式不对 | 422 | None | http=422 | 5ms | ✅ |

### registrationManagement（4/4 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/registrationManagement/getList` | 挂号列表 | 默认查询 | 200 | 200 | biz=200 | 7ms | ✅ |
| GET | `/api/registrationManagement/registrationList` | 我的挂号 | 患者查看 | 200 | 200 | biz=200 | 12ms | ✅ |
| POST | `/api/registrationManagement/create` | 创建挂号 | admin非患者返回500 | 200 | 500 | biz=500 | 14ms | ✅ |
| POST | `/api/registrationManagement/cancel` | 取消挂号-不存在 | uuid不存在（系统返回200） | 200 | 200 | biz=200 | 12ms | ✅ |

### report（4/4 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/report/outpatientVolume` | 门诊量 | 按日统计 | 200 | 200 | biz=200 | 14ms | ✅ |
| POST | `/api/report/finance` | 财务报表 | 按日统计 | 200 | 200 | biz=200 | 12ms | ✅ |
| POST | `/api/report/pharmaceutical` | 药品报表 | 按日统计 | 200 | 200 | biz=200 | 27ms | ✅ |
| POST | `/api/report/doctorWorkload` | 医生工作量 | 按日统计 | 200 | 200 | biz=200 | 113ms | ✅ |

### slotPool（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/slotPool/getList` | 号源池 | 默认查询 | 200 | 200 | biz=200 | 41ms | ✅ |
| POST | `/api/slotPool/adjust` | 号源调整-空参数 | 空参数返回500 | 200 | 500 | biz=500 | 11ms | ✅ |

### structuredMedicalRecord（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/structuredMedicalRecord/getList` | 结构化病历 | 默认查询 | 200 | 200 | biz=200 | 34ms | ✅ |

### surgeryApplication（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/surgeryApplication/getList` | 手术申请列表 | 默认查询 | 200 | 200 | biz=200 | 5ms | ✅ |

### surgerySchedule（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/surgerySchedule/getList` | 手术排程 | 默认查询 | 200 | 200 | biz=200 | 6ms | ✅ |

### temperatureRecord（0/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/temperatureRecord/getList` | 体温记录 | 默认查询 | 0 | None | biz=200 | 10ms | ❌ |

### triage（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/triage/keywords` | 导诊关键词 | 获取关键词列表 | 200 | 200 | biz=200 | 5ms | ✅ |
| POST | `/api/triage/suggest` | 智能导诊 | 症状推荐科室 | 200 | 200 | biz=200 | 13ms | ✅ |
| POST | `/api/triage/suggest` | 智能导诊-空症状 | 空字符串应失败 | 200 | 500 | biz=500 | 11ms | ✅ |

### triageDesk（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/triageDesk/getList` | 分诊台列表 | 默认查询 | 200 | 200 | biz=200 | 11ms | ✅ |
| POST | `/api/triageDesk/create` | 创建分诊 | 护士分诊 | 200 | 200 | biz=200 | 19ms | ✅ |

### user（7/7 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/user/getList` | 用户列表-默认 | 管理员查看所有用户 | 200 | 200 | biz=200 | 13ms | ✅ |
| GET | `/api/user/getList` | 用户列表-按角色 | 按角色过滤 | 200 | 200 | biz=200 | 8ms | ✅ |
| GET | `/api/user/getList` | 用户列表-关键字 | 按关键字搜索 | 200 | 200 | biz=200 | 15ms | ✅ |
| POST | `/api/user/updateRole` | 修改用户角色 | 修改 patient2 为 patient | 200 | 200 | biz=200 | 15ms | ✅ |
| POST | `/api/user/updateRole` | 修改角色-不存在 | 不存在的user_id | 200 | 500 | biz=500 | 12ms | ✅ |
| POST | `/api/user/resetPassword` | 重置密码 | 重置 patient2 密码 | 200 | 200 | biz=200 | 349ms | ✅ |
| POST | `/api/user/resetPassword` | 重置密码-不存在 | 不存在的user_id | 200 | 500 | biz=500 | 11ms | ✅ |

### userInfo（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/userInfo` | 获取用户信息 | 已登录用户 | 200 | 200 | biz=200 | 7ms | ✅ |
| POST | `/api/userInfo` | 无效token | accesstoken无效 | 401 | None | http=401 | 6ms | ✅ |

### vitalSign（3/3 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/vitalSign/getList` | 体征列表 | 按patient_id查询 | 200 | 200 | biz=200 | 19ms | ✅ |
| POST | `/api/vitalSign/create` | 录入体征 | 护士录入 | 200 | 200 | biz=200 | 18ms | ✅ |
| POST | `/api/vitalSign/create` | 录入体征-异常温度 | 温度超出范围 | 422 | None | http=422 | 13ms | ✅ |

### ward（2/2 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/ward/getList` | 病区列表 | 默认查询 | 200 | 200 | biz=200 | 47ms | ✅ |
| POST | `/api/ward/create` | 新增病区 | 正常新增 | 200 | 200 | biz=200 | 13ms | ✅ |

### wardRound（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| GET | `/api/wardRound/getList` | 查房记录 | 按admission_id查询 | 200 | 200 | biz=200 | 5ms | ✅ |

### windowRegistration（1/1 通过）

| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |
|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|
| POST | `/api/windowRegistration/create` | 窗口挂号 | 前台代挂号 | 200 | 200 | biz=200 | 17ms | ✅ |

---

## 三、失败用例详情

共 **8** 个用例未达预期：

### 1. POST /api/register - 正常注册

- **描述**：新患者注册
- **期望**：biz=200
- **实际**：HTTP=200, biz=500
- **响应**：`{"code": 500, "msg": "用户注册失败"}`

### 2. GET /api/appointmentManagement/appointmentList - 我的预约

- **描述**：默认查询
- **期望**：biz=200
- **实际**：HTTP=500, biz=None
- **响应**：`Internal Server Error`

### 3. POST /api/appointmentManagement/create - 创建预约

- **描述**：admin非患者返回500
- **期望**：biz=500
- **实际**：HTTP=0, biz=None
- **响应**：``
- **错误**：('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))

### 4. POST /api/prescriptionManagement/create - 创建处方

- **描述**：医生开处方
- **期望**：biz=200
- **实际**：HTTP=200, biz=500
- **响应**：`{"code": 500, "msg": "医生或病人信息不存在"}`

### 5. POST /api/medicalRecord/create - 创建病历

- **描述**：医生写病历
- **期望**：biz=200
- **实际**：HTTP=200, biz=500
- **响应**：`{"code": 500, "msg": "医生信息不存在"}`

### 6. POST /api/labOrder/create - 创建检验申请

- **描述**：医生开检查单
- **期望**：biz=200
- **实际**：HTTP=200, biz=500
- **响应**：`{"code": 500, "msg": "医生信息不存在"}`

### 7. GET /api/nursingRecord/getList - 护理记录

- **描述**：默认查询
- **期望**：biz=200
- **实际**：HTTP=500, biz=None
- **响应**：`Internal Server Error`

### 8. GET /api/temperatureRecord/getList - 体温记录

- **描述**：默认查询
- **期望**：biz=200
- **实际**：HTTP=0, biz=None
- **响应**：``
- **错误**：('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))

---

## 四、性能统计

| 指标 | 数值 |
|:----|:----:|
| 平均耗时 | **22ms** |
| P50 | **11ms** |
| P95 | **56ms** |
| P99 | **351ms** |
| 最快 | **3ms** |
| 最慢 | **421ms** |

### 最慢的 10 个接口

| 方法 | 路径 | 场景 | 耗时 |
|:----|:----|:----|:----:|
| POST | `/api/login` | 无token访问登录 | **421ms** |
| POST | `/api/doctorManagement/register` | 新增医生 | **351ms** |
| POST | `/api/user/resetPassword` | 重置密码 | **349ms** |
| POST | `/api/login` | 错误密码 | **319ms** |
| POST | `/api/login` | 正常登录 | **317ms** |
| POST | `/api/report/doctorWorkload` | 医生工作量 | **113ms** |
| GET | `/api/inpatientOrder/getExecutionList` | 医嘱执行列表 | **64ms** |
| GET | `/api/bed/getList` | 床位列表 | **63ms** |
| GET | `/api/prescriptionManagement/getList` | 处方列表 | **62ms** |
| GET | `/api/chargeManagement/getList` | 收费列表 | **56ms** |

---

## 五、测试结论

⚠️ 共 **8** 个用例未达预期。

失败用例可分为：

1. **业务码语义差异** — 期望 404 但系统返回 biz=500（本系统约定）
2. **接口字段不一致** — 部分接口字段命名与直觉不一致（已纠正）
3. **认证不强制** — 部分敏感接口未强制要求 token
4. **真实 bug** — 业务逻辑或异常处理缺陷

---

## 六、测试方法说明

### 测试范围

- ✅ **正常路径**：每个核心接口的成功调用
- ✅ **错误数据**：不存在的 ID、非法值、超出范围
- ✅ **参数缺失**：缺少必填字段，验证 Pydantic 校验
- ✅ **空数据**：空字符串、空列表
- ✅ **边界值**：金额负数、温度超范围

### 不在测试范围

- ❌ 并发/压测（详见 performance.md）
- ❌ 安全渗透测试（SQL 注入、XSS）
- ❌ 文件上传细节
- ❌ 体检/手术等深度业务流（仅覆盖列表）

### 执行方式

```bash
cd fastapi_be && uvicorn app.main:app --host 0.0.0.0 --port 8000
python tests/api/test_all_endpoints.py
```

### 输出文件

- `tests/api/test_results.json` — 原始结果（机器可读）
- `doc/api-test-report.md` — 本文档（人类可读）

### 测试数据

- 管理员：admin / admin123
- 患者：patient_id=2（身份证 510101200210157483）
- 医生：doctor_id=1，科室：department_id=1
- 药品：pharmaceutical_id=1
- 病区：ward_id=1，床位：bed_id=1
- 入院：admission_id=2f79ae7c-35b3-4731-8bd8-23f2004bc8ca

### 维护约定

1. 新增 API 后，在 `get_cases()` 末尾添加 T() 调用
2. 修改 schemas 字段后，同步更新 T() 的 body 参数
3. 修复 bug 后重跑测试确认通过

---

## 七、相关文档

- [API 完整文档](apiDoc.md)
- [架构文档](architecture.md)
- [测试指南](testing.md)
- [数据字典](data-dictionary.md)