# AI 平台开发与使用指南

## 当前交付边界

AI 平台提供 80 项候选能力的独立任务 Prompt、共享文本模型网关、专用模型接口契约、超级管理员管理台、权限范围内的患者资料、审核知识检索、持久化任务、引用展示和人工反馈。

文本能力可通过共享业务工作台调用。每个功能是否适合实际业务，仍取决于其模型配置、输入数据、已发布知识及验证状态。语音、影像、心电、预测和优化通过专用适配器接入，未配置适用模型及验证报告时不能执行。功能出现在目录中不表示已经完成专病或专用模型验证。

项目不自动创建外部模型账号，不预置真实临床知识或虚构模型回答。现有处方、医嘱、签名、收费和预约流程继续承担业务执行与权限校验。

## 本地启动

在 `fastapi_be` 中配置现有数据库及 JWT 环境后，先执行数据库迁移，再分别启动 API 和 worker：

```bash
python -m app.db_migrate
python -m uvicorn app.main:app --reload --port 8000
```

另一个终端使用相同环境启动：

```bash
python -m app.ai.worker
```

`python -m app.ai.worker --once` 最多处理一项任务，适合诊断；常驻 worker 默认每两秒轮询。已有未纳入 Alembic 管理的数据库按原部署手册核对、备份并接管，不直接跳过迁移检查。

前端在 `vue3-new-ui` 中运行 `npm run serve:rspack`。业务入口为 `/#/ai/workbench`，超级管理员管理入口为 `/#/ai/manage`。Docker Compose 已增加 `ai-worker`，并等待数据库迁移完成后启动。

## 超级管理员配置顺序

1. 部署环境将实际模型主机加入 `AI_PROVIDER_ALLOWED_HOSTS`。默认仅允许本机，远端端点使用 HTTPS；重定向不会被跟随。
2. 选择密钥方式：配置 `AI_MODEL_API_KEY`，或配置至少 32 字符的稳定 `AI_CREDENTIAL_KEY` 后在管理台加密保存 API 密钥。模型配置查询和配置审计不回显明文或密文密钥。
3. 在“模型服务”中新建文本服务或专用适配器。文本服务类型支持 Chat Completions 兼容协议与 Responses API；模型标识填写服务实际提供的名称。
4. 若服务获准处理患者和临床资料，显式开启该服务的患者资料权限。缩减直接标识不等于完全匿名化。
5. 在“知识审核”中创建有来源、版本、适用功能和有效期的知识草稿；核对全文后发布。只有已发布且仍有效的适用知识参与检索。
6. 在功能配置中选择模型、授权角色及每日调用上限。临床能力完成验证并登记依据后才能面向业务启用；超级管理员可使用明确标记的评估预览。
7. 根据实际诊疗关系使用患者资料。需要额外访问时，在“患者访问授权”中登记用途、范围和到期时间，授权最长 90 天。

普通管理员与业务角色不能管理上述 AI 配置。功能使用角色受固定业务边界与管理员配置共同约束；超级管理员的管理权不会通过普通管理员的 `admin` 权限继承。

## Prompt 生命周期

- 默认 Prompt 位于 `app/ai/catalog.py`，每个功能都有独立任务目标、需核查输入及具体产出要求。
- 固定系统契约每次调用始终附加，规定事实边界、来源、缺失信息、数据用途和禁止自动执行业务操作。
- 管理台修改任务 Prompt 时创建新的不可变版本；可以激活历史版本或回到默认 v0。
- 更换活动 Prompt 或模型会关闭关联能力，等待重新验证启用。旧任务保留其原版本与资料摘要。
- 请求输入与检索文档放在数据消息中，不能覆盖系统指令。模型不能指定 SQL、执行系统命令、访问任意 URL 或直接修改业务数据。

## 任务与证据

提交任务后，服务器先检查角色、患者关系、模型用途和所需知识，冻结资料、Prompt 和证据版本，再由独立 worker 处理。当前知识检索使用有版本的段落关键词检索，检索不到适用知识时明确拒绝相关任务。

患者摘要区分当前就诊与既往、已签名与草稿、已审核与未审核、处方记录与实际服药。治疗路径推荐要求指定本次就诊，并取得责任医生单独复核为“已明确”的诊断；单纯病历签名不会产生确诊状态。

病历与报告行传入的明确资料标识会校验患者归属，并优先纳入有限快照。快照显示截断范围，不能据有限近期记录断言不存在其他病史或用药。患者端不加载未签署病历、未审核报告及医护住院工作笔记。

模型返回必须满足 JSON 结构。引用 ID 必须来自本次服务器提供的来源；需要医学知识的回答必须引用已审核知识。ID 校验只证明引用属于已提供的材料，语义支持程度仍需人工核对。

worker 在执行前和保存结果前重新检查权限、配置、患者资料、确定性工具结果与知识有效性。患者资料、诊断确认、审方规则或目录改变时拒收旧结果；授权撤销、版本改变或知识停用后，旧任务不会静默使用新配置继续完成。`AI_MAX_QUEUE_AGE_SECONDS` 默认 900 秒，过期排队任务不发起模型调用。长时间中断的任务标记失败，避免自动重复可能计费的推理请求。

结果使用纯文本呈现，附来源查看入口、缺失信息和人工反馈。采纳反馈用于审计与质量分析，不代表临床结论已验证；也不会自动写入病历或处方。

## 已接入的临床资料与工具

| 内容 | 行为与边界 |
| --- | --- |
| 处方用法 | 保存每次剂量、单位、频次、途径和疗程；历史未知字段保持空值。药房审核、发药和 AI 使用同一套已保存用法复核 |
| 剂量规则 | 单位明确且与处方一致时才比较。采用十进制运算；未知、按需、单次频次及速率单位不推算每日量，不跨行推断成分累计 |
| 未完整剂量评估 | 保留原规则等级，标注未评估原因；禁止级规则输入不完整时仍阻止审核和发药。旧剂量规则需由药师补充单位 |
| 诊断复核 | 门诊和住院页面由责任医生单独记录诊断确认状态、依据和版本；原文改变使旧确认失效，全部历史版本保留 |
| 检验指标 | 手工录入和 LIS 接收支持项目编码、数值或定性结果、原单位、参考范围、带时区采样时间、方法、标本和原始标记。继承原报告双人审核状态 |
| 检验趋势 | 仅比较编码体系、项目编码、单位、检测方法和标本相同的已审核数值；重复采样时间和缺少可比条件时不计算方向，不更改原危急值规则 |
| 危急值辅助 | 展示原通知、确认、处理状态与时间；AI 不关闭或降低危急值，不代替原闭环流程 |
| 住院连接 | 限定所选住院的医嘱、执行、给药核对、护理评估与计划、病程、查房、出院记录、既有 ICU 评分及相应首页和收费资料 |
| 给药事实 | 核对通过不等同给药，须同时有已给药状态和实际时间才标记“已记录给药”；条码不发送给模型 |
| 随访与出院 | 读取既定随访及患者反馈；患者端仅在已出院住院记录中加载出院指导 |

检验数值保留最多 8 位小数，生产 PostgreSQL 使用 NUMERIC，SQLite 开发环境使用精确十进制文本映射，避免二进制浮点丢失。处方剂量最多 6 位小数；现有规则阈值数据库为 2 位小数，超出精度会拒绝保存，不静默四舍五入。

上述结构参考 [FHIR R4 Condition 的验证状态与就诊关系](https://hl7.org/fhir/R4/condition.html)、[Observation 的结果、单位与采样资料](https://hl7.org/fhir/R4/observation.html)、[Dosage 的用法结构](https://hl7.org/fhir/R4/dosage.html)。本系统采用现有院内字段与扩展表，未声明实现完整 FHIR 服务或术语映射。

## 主要代码与接口

| 位置 | 职责 |
| --- | --- |
| `app/ai/catalog.py` | 80 项功能及独立默认 Prompt |
| `app/ai/models.py` | 配置、Prompt、知识、任务、反馈、授权和审计表 |
| `app/ai/governance.py` | 密钥、版本、角色元数据与配置审计 |
| `app/ai/context.py` | 真实诊疗关系校验和患者资料快照 |
| `app/ai/patient_sources.py` / `clinical_tools.py` | 住院来源、检验趋势和既有危急值状态 |
| `app/clinical_observations.py` / `diagnosis_review.py` | 精确检验数据和责任医生诊断复核 |
| `app/ai/knowledge.py` | 适用、有效且已审核知识的段落检索 |
| `app/ai/gateway.py` | 有界 HTTP 调用、响应解析和引用校验 |
| `app/ai/runtime.py` / `worker.py` | 持久化任务、并发领取、执行与失效检查 |
| `app/routers/ai_admin.py` | 仅 `super_admin` 的治理接口 |
| `app/routers/ai.py` | 授权能力、患者选择、资料、任务和反馈接口 |
| `src/components/AIAssistant` | 工作台与业务页面共享的调用、来源和复核组件 |

主要业务接口：`GET /api/ai/features`、`GET /api/ai/patients`、`GET /api/ai/encounters`、`GET /api/ai/context`、`POST /api/ai/runs`、`GET /api/ai/runs/{id}` 和 `POST /api/ai/runs/{id}/feedback`。管理接口统一位于 `/api/ai/admin/`，以生成的 RBAC 矩阵为准。

## 专用适配器契约

配置类型为 `specialist`，登记实际模型版本、支持的功能 key 和验证报告。平台向配置基础地址的 `/tasks` 发送：

```json
{"schema_version":"1","feature_key":"ecg_analysis","engine":"signal","model":"实际模型版本","input":{"input":{},"context":{},"tools":{},"evidence":[]}}
```

适配器必须核对适用人群、原始资料类型和输入质量。响应包含 `schema_version`、相同的 `feature_key`、与配置一致的 `model_version`、布尔值 `applicable` 以及 `result`。`applicable` 不为 `true` 时任务失败，不退化为大模型编造结果。

`result` 的结构与文本任务一致：`summary`、`sections`（每项含 `title`、`content`、`source_ids`）、`warnings`、`missing_data`。原始图像、波形、数字切片、带结局标注的队列及模型性能必须由具体适配项目提供和验证；此接口契约不替代这些工作。

## 验证命令

```bash
# fastapi_be
pytest -q tests/test_ai_catalog.py tests/test_ai_admin.py tests/test_ai_gateway.py tests/test_ai_context.py tests/test_ai_runtime.py tests/test_ai_migration.py tests/test_rbac_drift.py
python scripts/generate_rbac_matrix.py --check
python scripts/export_ai_catalog.py --check
ruff check app/ai app/routers/ai.py app/routers/ai_admin.py
```

```bash
# vue3-new-ui，E2E_BASE_URL 指向已启动的前端
npm run build
npm run check:bundle
npm run test:e2e -- e2e/ai-*.spec.js e2e/diagnosis-review.spec.js
```

协议实现参考：[Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、[Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。本地隔离测试不会调用真实付费模型。
