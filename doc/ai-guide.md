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

院内临床路径通过“知识审核 → 从临床路径导入”另建待审核快照。导入保留当前模板的原始字段、版本、完整步骤及适用/排除条件；步骤必须是非空JSON数组或含`steps`数组的对象，重复字段、无效数值及过大/过深结构不自动解释。原JSON文本保留，解码展示中的数字按文本保留精度。选择适用AI功能、科室及有效期后保存，再核对全文并单独审核发布；模板的启用状态不表示完成审核。

快照绑定原路径、递增来源版本和内容哈希。原模板修改、停用或删除后，旧快照不再被检索，也不计为可用审核知识；停用后恢复相同原文仍需重新导入审核。已停用的路径知识版本不能直接重新发布。独立知识表单不能手工伪造院内路径来源地址。以上操作仅限超级管理员，不调用模型，也不改写原路径和患者入径状态。

“能力与启用”中的配置检查会逐项列出模型、凭据、用途权限、适配器声明、审核知识和临床验证缺口。检查只核对基础依赖；真正执行时仍按科室、患者、问题和时间筛选知识及资料。模型服务显示“已启用”仅表示配置开关，不表示完成真实联通或临床效果验证。

“任务与反馈”支持按能力、状态、发起用户、患者及包含的反馈类型分页查询全院任务。超级管理员可查看每次调用的原始 Prompt、请求模型、输出上限、验证记录、输入资料、工具结果、依据及历次反馈，也可取消接收正在排队或生成的结果。模型和 Prompt 的后续修改不会覆盖旧任务已经留存的快照。旧任务未保存的字段按缺失展示。

“反馈脱敏审核”提供评价目录、脱敏稿及版本审核。目录只给出原评价时间、评分和科室等元数据；读取原评论另记审计。按评价标识查询时可跨日期查找，未指定标识时默认近30天。先核对自动缩减直接标识的建议，补查第三方和间接识别线索后保存待审核版本；保存草稿不会调用模型或发布文本。审核页面须重新读取原评价，对照原意和身份线索，明确勾选两项确认并填写说明才能发布。自动建议和人工审核均不构成匿名化保证，也不证明反馈事实或责任已调查属实。

每次发布前核对原评价内容、评分、时间、患者/医生/就诊关联、有效科室及已知标识资料。修改文本必须另存新版本，发布新版本自动停用同一原评价旧的发布版本。原文、关联或版本文本校验变化时，旧稿不进入后续模型资料；来源无法核实的已发布版本仍可停用。任务调用前后重新校验，停用后排队任务不再发起调用，生成中的结果会被作废。普通使用者对包含失效片段的旧任务失去访问权，超级管理员仍可在冻结审计中追查当时使用的版本。

普通管理员与业务角色不能管理上述 AI 配置。功能使用角色受固定业务边界与管理员配置共同约束；超级管理员的管理权不会通过普通管理员的 `admin` 权限继承。

收费员可被配置使用“收费与漏记账核对”，其他 AI 能力不因此开放。收费员须由超级管理员授予“运营与收费”范围的限时患者访问；核对只加载所选账务和执行关联，不加载患者其他病史。已有功能配置的角色列表不会自动扩展，需在管理台明确选择。

药师可被配置使用药品耗材需求预测及库存分析，其医院级读取仅限明确品种的库存资料，不获得全院经营或财务数据权限。科室主任使用所属科室原始记录汇总；库存尚未按科室保存归属时不向科室范围提供全院库存。业务角色及配置仍共同限制实际可用功能，旧配置不会自动新增药师授权。

## Prompt 生命周期

- 默认 Prompt 位于 `app/ai/catalog.py`，每个功能都有独立任务目标、需核查输入及具体产出要求。
- 固定系统契约每次调用始终附加，规定事实边界、来源、缺失信息、数据用途和禁止自动执行业务操作。
- 管理台修改任务 Prompt 时创建新的不可变版本；可以激活历史版本或回到默认 v0。
- 更换活动 Prompt 或模型会关闭关联能力，等待重新验证启用。旧任务保留其原版本与资料摘要。
- 请求输入与检索文档放在数据消息中，不能覆盖系统指令。模型不能指定 SQL、执行系统命令、访问任意 URL 或直接修改业务数据。

## 任务与证据

提交任务后，服务器先检查角色、患者关系、模型用途和所需知识，冻结资料、Prompt 和证据版本，再由独立 worker 处理。当前知识检索使用有版本的段落关键词检索，检索不到适用知识时明确拒绝相关任务。

患者摘要区分当前就诊与既往、已签名与草稿、已审核与未审核、处方记录与实际服药。治疗路径推荐要求指定本次就诊，并取得责任医生单独复核为“已明确”的诊断；单纯病历签名不会产生确诊状态。

明确选择院内路径或原入径记录时，治疗推荐还要求该路径当前来源匹配、适用于本功能和科室、且已审核发布的知识版本。其他通用资料不能替代所选路径的审核；所选路径知识优先纳入检索，结果有分节时必须包含该路径审核版本的引用，否则拒收。来源标识校验不等同于证明模型陈述与原文语义一致，仍须人工逐项核对纳入、排除条件及建议依据。

病历与报告行传入的明确资料标识会校验患者归属，并优先纳入有限快照。快照显示截断范围，不能据有限近期记录断言不存在其他病史或用药。患者端不加载未签署病历、未审核报告及医护住院工作笔记。

资料预览与提交使用相同的服务器来源解析。病案首页、手术申请、排台、围术期用药和门诊/住院费用等来源通过 `POST /api/ai/context` 的 `source_refs` 传入；原有 `GET /api/ai/context` 保留五类既有来源参数。前端从能力元数据读取支持的引用键，服务端核对真实患者、父记录及就诊关系。

最近任务按所选功能、患者和本次就诊筛选。改变患者、处方或服务选项后，旧资料预览、提交回执与任务刷新不能覆盖当前界面；已经保存的任务仍保留原始范围和权限。

医院级资料使用 `POST /api/ai/operational-context` 预览，输入和提交共用日期、科室、品种及计划区间筛选。预览不创建推理任务，也不连接模型；能力未启用时，当前角色仍可核查其有权读取的原始资料。运营报表、病区床位和药品库存预警页面均有入口，工作台也支持直接选择范围。

模型返回必须满足 JSON 结构。引用 ID 必须来自本次服务器提供的来源；需要医学知识的回答必须引用已审核知识。ID 校验只证明引用属于已提供的材料，语义支持程度仍需人工核对。

worker 在执行前和保存结果前重新检查权限、配置、患者资料、确定性工具结果与知识有效性。患者资料、诊断确认、审方规则或目录改变时拒收旧结果；授权撤销、版本改变或知识停用后，旧任务不会静默使用新配置继续完成。`AI_MAX_QUEUE_AGE_SECONDS` 默认 900 秒，过期排队任务不发起模型调用。长时间中断的任务标记失败，避免自动重复可能计费的推理请求。

医院级任务同样重新读取日统计、原始汇总、床位、排班或所选库存；变化后拒收旧结果。历史任务读取还重新核对原科室或全院范围，调离科室或失去全院权限不会保留旧结果的访问权。运营引用包含范围、日期及读取时刻，当前界面展示的是任务冻结版本。

任务额外冻结当时的系统 Prompt、目录版本、请求模型配置、有效输出上限和人工验证记录。worker 输出限制与排队时不一致时拒绝调用。取消接收不会撤回已经发出的模型请求；若服务返回 Token 用量，取消任务仍保留该用量。统计汇总模型已报告的 Token，未报告不作为零费用依据。

结果使用纯文本呈现，附来源查看入口、缺失信息和人工反馈。采纳反馈用于审计与质量分析，不代表临床结论已验证；也不会自动写入病历或处方。

## 已接入的业务资料与工具

| 内容 | 行为与边界 |
| --- | --- |
| 处方用法 | 保存每次剂量、单位、频次、途径和疗程；历史未知字段保持空值。药房审核、发药和 AI 使用同一套已保存用法复核 |
| 剂量规则 | 单位明确且与处方一致时才比较。采用十进制运算；未知、按需、单次频次及速率单位不推算每日量，不跨行推断成分累计 |
| 未完整剂量评估 | 保留原规则等级，标注未评估原因；禁止级规则输入不完整时仍阻止审核和发药。旧剂量规则需由药师补充单位 |
| 诊断复核 | 门诊和住院页面由责任医生单独记录诊断确认状态、依据和版本；原文改变使旧确认失效，全部历史版本保留 |
| 转诊与MDT | 同患者核实明确转诊/MDT引用，最多6条转诊和6条会诊；科室按实际CSV/JSON标识映射，不能从描述文字抽取数字后编造科室。原申请诊断不提升为本次确认诊断，审批通过不作实际接诊，退回/未完成病例的结果保留原状态 |
| 会诊时间与权限 | 原记录没有对应就诊、实际接诊/会诊时刻、个体参会确认和结果签署信息时保持未知，不按日期推定。读取仍须已有诊疗关系或有效的限时用途授权，审批记录本身不新增AI资料访问权 |
| ADR资料 | 同患者核实明确上报，最多8条，保留上报症状、药品目录映射、原严重度和处理说明；药品引用缺失不补名称，上报时间不当起病或暴露时间，缺首末剂、停药/再暴露信息时不计算因果评分 |
| ADR与过敏 | 确认ADR不再自动写入过敏史；实际过敏仍独立登记及核查。原状态2曾同时用于已处理和已排除，新字段保存明确结果、处理者及时间，未核实历史值保持未知；旧过敏记录不自动清除 |
| 院内临床路径 | 当前模板元数据和已审核知识分开；未审核原步骤不进入患者资料，治疗依据须引用当前匹配且适用的已发布快照。当前模板不作为入径当时的历史版本，预计天数不作个体出院目标 |
| 入径与变异 | 同患者最多6条原入径记录，优先纳入明确所选记录；核实所记住院、患者和当前访问关系，与所选就诊不一致则拒绝。不根据日期补关联，未记住院则保留未知 |
| 原完成计数 | 保留NULL、明确0、未知分母及计数矛盾；总数0不计算比例，完成数大于总数不截断为100%。比例仅是原计数，不证明逐项执行、疗效或出院适宜性；原入径/退出日期不作实际治疗首末时刻 |
| 检验指标 | 手工录入和 LIS 接收支持项目编码、数值或定性结果、原单位、参考范围、带时区采样时间、方法、标本和原始标记。继承原报告双人审核状态 |
| 检验趋势 | 仅比较编码体系、项目编码、单位、检测方法和标本相同的已审核数值；重复采样时间和缺少可比条件时不计算方向，不更改原危急值规则 |
| 危急值辅助 | 展示原通知、确认、处理状态与时间；AI 不关闭或降低危急值，不代替原闭环流程 |
| 住院连接 | 限定所选住院的医嘱、执行、给药核对、护理评估与计划、病程、查房、出院记录、既有 ICU 评分及相应首页和收费资料 |
| 给药事实 | 核对通过不等同给药，须同时有已给药状态和实际时间才标记“已记录给药”；条码不发送给模型 |
| 随访与出院 | 读取既定随访及患者反馈；患者端仅在已出院住院记录中加载出院指导 |
| 围术期资料 | 核对手术申请、排台、用药和麻醉记录的同患者/同申请/同住院关系；手术团队访问随有效排台关系变化 |
| 围术期时间核对 | 复用原有 30–120 分钟统计窗口；参照为排台 `start_time`，不是另行采集的切皮时刻。多条排台未明确配对、计划用药或时间缺失时不计算，不将统计窗口认定为个体临床适宜性 |
| 首页与 ICD | 读取明确首页及其已绑定编码，标记字典停用、名称变更和条目缺失；仅从当前有效院内字典作有界文字匹配，原始候选和依据独立于模型文本展示 |
| DRG 证据 | 保留已记录分组及当前关联规则；旧分组没有冻结规则版本时明确历史依据缺口，不以预期结算、利润或收益生成诊断及编码 |
| 住院收费 | 限定所选住院或费用，核对保存金额、数量单价原始乘积、关联医嘱和全量执行状态汇总；退费不列为补费候选，金额差异需核实舍入和计价政策 |
| 未保存收费关联 | 仅列同时有已执行状态和实际执行时间、且无任何收费关联的医嘱；不据此认定漏收费，须核实免费项目、打包计费和历史关联缺失 |
| 门诊账务 | 同时核实处方、挂号和收费的患者一致性，按所选收费读取支付/票据分状态汇总；现金及历史流水缺失不等于未支付，处方缺少就诊关联时不按日期猜测 |
| 财务资料范围 | 不发送支付二维码、外部交易标识或票据单号；不以当前药价反算历史账单，不自动收费、退款、开票或作废 |
| 院内导航 | 调用现有方向性路线图，展示实际节点、原路线步骤及启用问答；开放时间、无障碍条件和实时封路没有建模时明确未知，办理材料仍需审核知识 |
| 预约候选 | 使用明日至第 6 日的真实周期排班共享库存，排除已审批的医生当日停诊；已审批加号已落入库存，不重复叠加，不把候选当锁号或预约成功 |
| 运营汇总 | 全院授权可读既有日统计，科室授权仅按所属科室原始记录汇总；挂号记录不等于到诊人数，未汇总日期和未知等待时间不补零 |
| 小时级需求 | 保留原钟点、当前记录状态和截断范围；不推断可靠历史时区，不补无记录小时为零，不把部分序列当完整训练数据 |
| 床位容量 | 分别保留配置床数、加载床行数及原状态计数；停用病区的空闲状态不作为可用床，空闲状态不等于已核实可收治名额 |
| 周期排班 | 只读已有医生周期排班、共享余量及计划区间的停诊/加号申请；档案职称不代替已核验资质，时段编码不换算工时，缺少请假、资质及工时上下限时明确未验证可行 |
| 手术排台资料 | 分开读取历史已完成排台起止、计划区间排台和未定日期申请；核实同患者住院与申请/排台关联，住院科室优先于申请医生当前科室，不发送患者、住院标识或诊断文本 |
| 手术资源交叠 | 只检查所载范围内、状态符合且原起止完整的区间，识别手术室及人员交叠，并合并同账号跨医生/护士分工；原起止不当作预约、切皮或预测时长，无交叠不等于具备可行性，独立手术室/设备目录与资质可用性仍缺失 |
| 满意度评分 | 仅聚合可核实同患者同医生关联的评价；挂号科室优先，无挂号时注明使用医生当前科室。评分缺失/越界不进入均值，无记录日不补零，未知均值不按零展示；无全体就诊分母，不称总体满意率 |
| 评价原文 | 业务分析不自动加载未审核原文；仅发送当前有效的已发布脱敏稿，并为每条片段提供独立引用。核对最多60条最新已发布候选后纳入最多20条，截断可见，不外推总体主题占比；片段不含患者/医生/评价/就诊标识，超级管理员的原文读取用于审核并留审计 |
| 反馈主题 | 主题仅由所载审核片段归纳，称为“已审核脱敏摘录/整理文本”，不宣称原话未作修改；无有效片段时只解释评分和缺口。来源不是完整投诉工单，缺少调查事实时不认定原因或责任 |
| 不良事件RCA | 必须明确选择同患者事件，仅加载该事件上报、处理记录及最多6条关联RCA，不随之加载整份病史。上报时间不等于发生时间；无就诊外键时拒绝人为绑定某次就诊，已闭环、根因文本或PDCA阶段不视为已独立核实 |
| 所选库存 | 单次最多 20 个真实药品或耗材；保留目录与批次合计差异、冻结及未知效期，无批次或未知库存不按零值处理，未记录药品计数单位时不补写成盒或片 |
| 库存历史 | 分别保留出入库原数量、前后库存差额及一致性计数；关联不一致的台账排除并标记，耗材追溯的 out/use 不直接相加当消耗，不发送患者、操作者或处方流水引用 |
| 采购资料 | 区分待审批、已审批、已入库及已取消，实收未知不代入计划数量；订单事件时间不等于承诺交期，缺少已验证需求和采购约束时不编造采购量 |

手术、首页/ICD、门诊与住院费用、院内导航、预约页面均有对应 AI 入口。编码、收费、路线和号源的原始工具结果附引用查看入口；模型解释不会覆盖这些原始结果。编码绑定、分组、收退款及预约仍通过原业务流程操作。

运营历史默认近 30 天，可选不含未来且最多 367 天的正序区间。医院数据问答的区间若完全早于当前业务日，不加载当前病区或床位快照，也不因无关的当前床位变化使历史分析失效；床位需求预测则单独保留当前容量供核查。排班/手术排台计划与历史资料分开，默认计划为业务日起 14 天，单次最多 31 天且不晚于业务日后 366 天。大范围资料可能超过模型输入预算，需缩小日期、科室或品种；原始清单若截断会明确标记。

手术页的“AI 排台分析”、运营页的评价分析，以及已关联患者的不良事件行“AI 事件复盘”，都能先查看资料再提交。事件行入口固定患者和事件，不展示就诊归属选择，结果同时展示冻结的原上报和原分析，并可检查引用。未绑定患者的组织事件仍待独立访问范围及数据连接，不强行归属某位患者。手术排台和反馈分析均受模型服务患者数据用途开关控制。当前默认目录及Prompt版本为 `2026.10.17`，旧队列不会沿用更新前的固定任务契约。

临床路径模板页提供“AI 治疗方案比选”，固定所选路径后选择已授权患者和本次就诊。工作台也可选择当前科室及功能已有审核版本的路径；选择就诊后重新核对审核范围。路径执行行的“AI 路径复评”固定患者、所记住院、原入径和路径标识，补充JSON不能替换这些绑定引用。预览与生成使用相同标识，原模板元数据、原入径与变异、未知计数及引用独立展示，结果保存任务当时版本。新增、入径、变异、退出及用药仍走原人工业务流程。

生成前后重新核对路径知识、模板来源版本、入径计数及患者资料。排队期间变化不会发起模型调用，在途变化会拒收结果；模型已报告的Token用量仍保留。原入径没有在任务请求中指定本次就诊时，读取历史结果仍重新校验其中明确关联住院的访问权。原表没有冻结入径当时的模板或逐项执行，后续仍需补齐实际治疗时间线和效果评价资料。

转诊、MDT和ADR行提供绑定原患者与记录的AI入口；补充JSON不能替换行中绑定的这三类资料引用。预览和生成使用同一组标识，模型结果之外独立展示原记录及依据。转诊前端入口已对齐原临床接口，医生和科主任可访问；患者账号不加载内部转诊工作列表。所选就诊可补充临床背景，不代表这些无就诊关联的记录属于该次就诊。历史资料超出条数限制时仍优先纳入明确所选记录，并展示截断。

ADR列表对管理员保留既有管理范围；药师只读现有处方业务范围内患者的记录，范围取处方原状态0/1/2，与既有药事AI诊疗关系校验一致。患者不再有该处方业务关系时，下一次读取即排除相应记录。AI用途授权不扩展这个业务列表范围，确认/处理/排除仍由原管理角色执行。历史状态2需在“核实历史结果”中明确选择并填写说明。处理只修改ADR记录，不自动新增或删除过敏资料。

药物过敏与不良反应分开记录的设计参考[NICE CG183建议1.2.5](https://www.nice.org.uk/guidance/CG183/chapter/recommendations)。这里用于资料分类，具体患者的过敏和因果判断仍需单独核实；该网页未自动导入或发布为院内诊疗知识。

上述连接提供真实输入及缺口，未提供训练模型、校准结果、完整耗材消耗账或已审核的人力约束。预测与优化仍需专用适配器、验证报告及适用数据；不能据资料预览或目录登记宣称已经具备预测效果或生成可行排班。

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
| `app/ai/consultation_sources.py` | 同患者转诊/MDT原状态、实际科室引用和审批/结果资料 |
| `app/ai/adr_sources.py` / `app/adr_status.py` | ADR原报告、明确处理结果及历史歧义区分 |
| `app/ai/audio_files.py` / `audio_assets.py` | 私有原音频、格式与解码校验、归属及撤回后的读取权限 |
| `app/ai/ecg_files.py` / `ecg_assets.py` | 私有WFDB成对原文件、原导联校准与缺失采样、诊疗团队及来源版本校验 |
| `app/ai/pathway_sources.py` / `pathway_knowledge.py` | 原路径入径资料、来源快照、审核匹配与所选路径知识核对 |
| `app/pathway_progress.py` | 保留未知或矛盾计数的进度口径，供业务列表和AI资料共用 |
| `app/ai/procedural_sources.py` / `care.py` | 手术申请/排台/围术期资料及手术团队关系 |
| `app/ai/coding_sources.py` | 首页编码、有效 ICD 字典候选与分组规则来源 |
| `app/ai/billing_sources.py` / `outpatient_billing.py` | 有范围的费用、执行、支付和票据只读核对 |
| `app/ai/service_sources.py` | 实际导航路线、院内问答和预约候选 |
| `app/ai/operational_sources.py` | 科室范围、运营窗口、日统计、床位及历史读取权限 |
| `app/ai/roster_sources.py` | 原始小时需求、周期排班及计划区间变更 |
| `app/ai/inventory_sources.py` | 明确品种的库存、批次、带符号台账和采购记录 |
| `app/ai/surgical_resources.py` | 手术申请、计划/历史排台及原时间同资源交叠线索 |
| `app/ai/feedback_sources.py` | 可核实评价评分汇总及当前有效的审核片段资料 |
| `app/ai/review_curation.py` | 原评价关联核验、脱敏版本、发布/停用与旧结果访问复查 |
| `app/ai/incident_sources.py` | 明确所选事件及关联RCA陈述、核验缺口 |
| `app/clinical_observations.py` / `diagnosis_review.py` | 精确检验数据和责任医生诊断复核 |
| `app/ai/knowledge.py` | 适用、有效且已审核知识的段落检索 |
| `app/ai/gateway.py` | 有界 HTTP 调用、响应解析和引用校验 |
| `app/ai/runtime.py` / `worker.py` | 持久化任务、并发领取、执行与失效检查 |
| `app/ai/readiness.py` | 超级管理员的基础配置依赖检查 |
| `app/routers/ai_admin.py` | 仅 `super_admin` 的治理接口 |
| `app/routers/ai_feedback_admin.py` | 仅超级管理员的评价原文读取、脱敏稿及审核接口 |
| `app/routers/ai_audio.py` | 授权录音登记、私有读取、撤回和超级管理员清除流程 |
| `app/routers/ai_ecg.py` | 原始心电登记、经鉴权的采样窗口与成对导出、撤回及超管清除恢复 |
| `app/routers/ai.py` | 授权能力、患者选择、资料、任务和反馈接口 |
| `src/components/AIAssistant` | 工作台与业务页面共享的调用、来源和复核组件 |
| `src/components/AIRunHistory` | 全院任务、原始调用快照与人工反馈查看 |
| `src/components/AIServiceFindings` | 原始导航和预约候选及来源展示 |
| `src/components/AIOperationalFindings` | 原始运营、床位、库存、排班、手术资源及评分资料与引用展示 |
| `src/components/AIIncidentFindings` | 冻结事件上报、处理与原RCA分析的只读展示 |
| `src/components/AIConsultationFindings` / `AIAdrFindings` | 独立于模型文案的转诊、MDT和ADR原始资料与引用 |
| `src/components/AIPathwayFindings` | 原模板元数据、审核版本、入径变异、原计数及引用 |
| `src/components/AIReviewCuration` | 逐条整理、原文对照、审核发布和停用界面 |
| `src/components/AIAudioInput` / `AIAudioPlayer` | 显式麦克风采集、原文件登记选择及经鉴权的听音与下载 |
| `src/components/AISpeechFindings` / `AIAudioManagement` | 分段草稿、未知说话人、原音引用和超级管理员录音治理 |
| `src/components/AIEcgInput` / `AIEcgViewer` | 成对登记、患者切换隔离、原始采样窗口与导联校准显示 |
| `src/components/AIEcgFindings` / `AIEcgManagement` | 冻结原始依据、候选导联与样本定位、超管原文件治理 |

主要业务接口：`GET /api/ai/features`、`GET /api/ai/patients`、`GET /api/ai/encounters`、`POST /api/ai/context`、`POST /api/ai/operational-context`、`GET /api/ai/service-options`、`POST /api/ai/runs`、`GET /api/ai/runs/{id}` 和 `POST /api/ai/runs/{id}/feedback`。管理接口统一位于 `/api/ai/admin/`，以生成的 RBAC 矩阵为准。

全院任务查询和原始快照分别使用 `GET /api/ai/admin/runs`、`GET /api/ai/admin/runs/{id}`，仅限 `super_admin`。业务使用者的任务接口不返回模型服务地址、冻结的系统 Prompt 或完整原始输入快照。

评价审核接口包括 `GET /api/ai/admin/review-sources`、`GET /api/ai/admin/review-sources/{id}`、`GET /api/ai/admin/review-excerpts`、`GET /api/ai/admin/review-excerpts/{id}`、`POST /api/ai/admin/review-excerpts`、`POST /api/ai/admin/review-excerpts/{id}/review`，全部仅限超级管理员。新增迁移为 `20261020_ai_review_excerpts`，升级和回滚已在隔离数据库验证，不覆盖原评价数据。

`POST /api/ai/context`的`source_refs`及任务`input`另支持规范正整数字符串`referral_id`、`mdt_id`、`reaction_id`、`pathway_id`、`pathway_enrollment_id`。患者端不加载这些内部工作资料。资料预览返回已授权、已缩减直接标识的原始依据，方便逐项核查，不创建模型任务。

`GET /api/ai/pathway-options`按功能、患者和所选就诊返回有限模板元数据及当前范围的审核可用性，不返回步骤。超级管理员独有`GET /api/ai/admin/pathway-sources`和`POST /api/ai/admin/pathway-sources/{id}/import`，导入须带刚读取的`expected_source_hash`。发布继续使用原知识审核接口，并验证正文哈希及原路径未变化。

迁移`20261020_adr_resolution`添加ADR明确结果、说明、处理者和时间，旧行保持NULL；`20261020_pathway_knowledge`添加可空的知识来源绑定，不把原独立知识改成路径；`20261020_pathway_revision`给原路径添加来源版本，已有行从1开始，不补造历史版本。`20261020_ai_audio_assets`新增录音元数据，`20261020_audio_governance`另存原清除请求说明；当前迁移头`20261020_ai_ecg_assets`只新增原始心电元数据与索引。新库使用项目的`python -m app.db_migrate`引导流程，已有库继续沿当前版本升级；隔离往返测试保留既有患者资料，未对真实业务数据库执行迁移。

AI接口保留原知识、引用及反馈正文中时间戳的小数部分，返回原文与其版本哈希对应。经结构验证的UUID和哈希保留原值，不因随机数字类似手机号而被缩减。任务同时冻结适用科室，调用前后按所选就诊或当前医生资料重新核对；仅科室调动、文字未变化的独立问答也会停止旧任务或拒收在途结果。

## 医疗语音录入与录音治理

“医疗语音录入”现在需要选择已授权患者和明确的`audio_asset_id`。门诊和住院病历行各有独立的“AI 录音转写”，固定原患者与所记就诊；不沿用病历正文作为语音识别输入。工作台也可选择已有录音。转写只自动提供所选原录音与其技术资料，不附带其他临床历史；用户补充问题不能当作实际听到的发言。

1. 展开“登记新录音或使用麦克风采集”，核对患者、所记就诊及录音采集和处理授权，明确勾选并填写说明。说明为登记人的核对记录，不表示系统独立核实了授权或真实身份。
2. 选择授权原文件，或主动点击“开始录音”。麦克风依赖浏览器能力及安全上下文；采集使用浏览器报告支持的编码，停止后仍需单独登记。切换患者或就诊、关闭面板及离开页面会停止采集并丢弃未登记录音；上传迟到回执不会绑定新患者。
3. 文件登记成功后明确选择原录音，先查看本次资料和原音，再提交转写。上传、目录读取和听音不创建模型任务。原文件时间可留空；提供时须有时区，不用上传时间补写。浏览器采集的时间来自采集端时钟，未独立核验。
4. 配置本功能的专用语音服务、患者资料传输权限及验证记录。原音可能含直接标识；提交转写会把原音附件发送给所选服务。默认未启用临床能力，超级管理员仍需按原流程配置和评审。
5. 结果显示相对解码音频的片段时间、说话人分组及不确定说明，可听对应片段、查看元数据引用并复制完整转写草稿。说话人身份与职业保持未知；不能据标签认定医生意见或患者陈述。片段范围校验不证明转写完整或识别准确，须听音核对后再走原文书书写和签署流程。

支持WAV、MP3、M4A、Ogg/OGA和WebM的单一纯音频轨。服务端检查固定格式、声道/采样资料和实际解码输出，浏览器WebM未保存时长头也可校验；解码校验不改写或保存处理后的副本，原字节与哈希保留。文件名不写入登记元数据；原容器和声音本身仍可能有识别线索，不构成匿名化。私有文件采用0600权限，目录0700，不经通用报告下载命名空间提供。

| 配置 | 默认值与作用 |
| --- | --- |
| `AI_AUDIO_STORAGE_DIR` | `private/ai-audio`；API与worker共享且可读取的私有目录，必须与上传和Web静态目录分开 |
| `AI_AUDIO_MAX_BYTES` | 67,108,864（64MiB）单文件上限 |
| `AI_AUDIO_MAX_DURATION_SECONDS` | 3600秒实际解码时长上限，需与模型验证范围相符 |
| `AI_AUDIO_USER_QUOTA_BYTES` | 536,870,912（512MiB）每登记人额度，按未清除的登记原文件字节计算 |
| `AI_AUDIO_PROCESS_TIMEOUT_SECONDS` | 30秒原格式探测/解码处理时限；超时明确失败 |

镜像安装FFmpeg，Compose的API与worker共享`ai_audio_private`卷并使用同一路径；私有目录及通用上传资料排除于镜像构建上下文。Nginx支持录音表单开销、同源麦克风和本地Blob播放；前端读取原音经`accesstoken`请求头鉴权，令牌不放入播放URL。关闭音频窗口或切换来源会停止播放并释放临时链接。格式处理参考[FFmpeg协议限制](https://ffmpeg.org/ffmpeg-protocols.html)与[ffprobe资料读取](https://ffmpeg.org/ffprobe.html)，浏览器采集使用[MediaStream Recording](https://www.w3.org/TR/mediastream-recording/)接口。

录音限登记人与超级管理员在当前诊疗关系或有效用途授权内使用；患者用途授权不转移他人登记的录音。功能使用角色配置另行限制登记和转写，普通管理员不能管理全院录音。超级管理员在“录音治理”中检查原授权说明和元数据、撤回及按版本清除原文件。撤回不释放文件额度；清除流程先持久化“清除中”，成功删除后标记“已清除”，存储失败可按当前版本恢复。原撤回原因与原清除原因分别保留。

撤回会阻断排队任务，在途结果重新检查后拒收；原文件、录音版本、当前诊疗关系或适用科室变化也会停止旧任务或拒收结果。已报告用量仍保留。普通用户不能继续读取已撤回来源的旧转写，超级管理员可追查冻结文字和元数据；原文件清除后不能播放。撤回无法收回已经发出的服务请求或已读取资料，清除当前原文件不会删除审计和既存任务文字。

录音接口：`GET /api/ai/audio-options`、`POST/GET /api/ai/audio-assets`、`GET /api/ai/audio-assets/{id}`、`GET /api/ai/audio-assets/{id}/content`、`POST /api/ai/audio-assets/{id}/withdraw`。全院目录与原文件清除分别为`GET /api/ai/admin/audio-assets`、`POST /api/ai/admin/audio-assets/{id}/purge`，仅限超级管理员。状态操作须有`expected_revision`和明确原因；内容变更与患者/就诊重绑不通过更新原文件实现。

## 专用适配器契约

配置类型为 `specialist`，登记实际模型版本、支持的功能 key 和验证报告。平台向配置基础地址的 `/tasks` 发送：

```json
{"schema_version":"1","feature_key":"ecg_analysis","engine":"signal","model":"实际模型版本","instructions":"实际冻结的固定系统Prompt与任务Prompt","input":{"input":{},"context":{},"tools":{},"evidence":[]}}
```

适配器必须核对适用人群、原始资料类型和输入质量。响应包含 `schema_version`、相同的 `feature_key`、与配置一致的 `model_version`、布尔值 `applicable` 以及 `result`。`applicable` 不为 `true` 时任务失败，不退化为大模型编造结果。

`result` 的结构与文本任务一致：`summary`、`sections`（每项含 `title`、`content`、`source_ids`）、`warnings`、`missing_data`。原始图像、波形、数字切片、带结局标注的队列及模型性能必须由具体适配项目提供和验证；此接口契约不替代这些工作。

### 语音附件契约v2

`medical_transcription`使用同一`/tasks`路径的`multipart/form-data`：`task`部分为JSON，含`schema_version:"2"`、功能、引擎、实际模型、完整`instructions`、`store:false`及冻结的`input`；`audio`部分为经核实的原文件，文件名为固定`recording`加原格式后缀。`input.context.audio_source`和`evidence`给出原文件标识、SHA-256、字节数、解码时长、采样与声道、版本和引用标识，不传私有磁盘路径或凭据。

接收端须校验实际收到字节的SHA-256、长度、原格式及模型适用范围，只解码该附件，不抓取输入中的任意URL。`store:false`是接收端需落实的处理约定，客户端标记不能证明服务实际保留策略。响应示例：

```json
{
  "schema_version": "2",
  "feature_key": "medical_transcription",
  "model_version": "与登记一致的实际模型",
  "applicable": true,
  "result": {"summary": "待听音复核的转写草稿", "sections": [], "warnings": [], "missing_data": ["说话人角色未经核实"]},
  "transcription": {
    "asset_id": "原录音UUID",
    "content_hash": "实际收到原文件的64位SHA-256",
    "time_basis": "relative_decoded_audio",
    "speech_detected": true,
    "language": "zh-CN",
    "segments": [{"start_ms": 0, "end_ms": 200, "speaker": "speaker_1", "speaker_role": "unknown", "text": "实际识别且待核对的内容", "uncertain": true, "uncertainty_note": "具体不确定处", "source_id": "提供的原音引用标识"}]
  },
  "usage": {"input_tokens": 5, "output_tokens": 7}
}
```

分段使用严格的整型毫秒，按开始时间排序且不超过原解码范围，可保留重叠发言。每段引用必须是该原录音，身份角色只接受`unknown`，不确定片段须给出说明。声明未检出语音时须为空片段。响应仍受512KiB及1000段上限约束，超限失败，不静默截断。输出不合法也保留已经正确解析的服务报告用量。上述JSON只是协议示例，不是识别质量或验证数据。

本地`fw:`模型另须返回`transcription.processing`，外部v2适配器未提供时界面明确显示处理范围未知。处理报告包含`engine`、`engine_version`、固定40位`model_revision`、`model_digest`、`runtime_digest`、`decoding_options_hash`和本次完整系统及任务Prompt的`instructions_digest`，以及`decoded_duration_ms`、`processed_duration_ms`、`submitted_samples`、`sample_rate`、`iterator_exhausted`、`vad_filter`、`translation`、`diarization`、`prompt_handling`、`timestamp_policy`。平台核对实际登记模型、原音时长、16kHz样本计数、完整迭代及本次Prompt哈希；不接受只处理部分输入的本地结果。完整处理是服务对输入范围的报告，不证明逐字完整、VAD无漏检或医学识别准确。

### 可选本地CPU语音服务

仓库提供`app.ai.speech_server`和独立的识别子进程。API与业务worker仍通过已登记的`specialist`网关调用，不要求给主业务运行环境安装识别依赖；默认不启动服务或启用临床能力。模型只从经核实的本地文件加载，推理启用离线模式，不接受请求中的模型路径或URL。一次最多处理一份原音，繁忙时明确拒绝而不重复排队；识别超时或进程任务取消时终止子进程组，临时原音与响应文件在处理结束后释放。

运行依赖在`requirements-speech.txt`固定；实际权重清单、各引擎库版本、语言、解码配置和CPU线程数共同形成`fw:<运行哈希>`。准备工具要求明确的仓库及40位提交哈希，复制并校验配置、权重、tokenizer和词表，不覆盖原版本。文件、依赖或识别配置变化须登记新的实际模型标识；服务核对与实际任务均不静默使用其他版本。

下面的小模型仅供非临床工程联调，不能据此选择医疗生产模型或推定中文术语效果。示例权重来源及许可见[固定版本模型卡](https://huggingface.co/Systran/faster-whisper-tiny/tree/518d6e0b5a068b278f66842b17377f9523de5cd1)，引擎行为参考[faster-whisper官方实现](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1)。

```bash
cd fastapi_be
python -m venv .venv-speech
.venv-speech/bin/python -m pip install -r requirements.txt -r requirements-speech.txt
.venv-speech/bin/python scripts/prepare_speech_model.py \
  --repository Systran/faster-whisper-tiny \
  --revision 518d6e0b5a068b278f66842b17377f9523de5cd1 \
  --destination "$PWD/private/ai-models/engineering-tiny"

# 先通过部署系统注入AI_PROVIDER_LOCAL_SPEECH_API_KEY，至少32字符的独立随机密钥。
# API/worker如使用环境变量引用，也须注入相同变量；不要把密钥写入Prompt或版本库。
export SPEECH_MODEL_DIR="$PWD/private/ai-models/engineering-tiny"
export SPEECH_LANGUAGE=zh
.venv-speech/bin/python -m app.ai.speech_server --describe
.venv-speech/bin/python -m app.ai.speech_server
```

服务配置示例为`.env.speech.example`，进程仅读取已导入的环境变量，不自动加载该文件。默认语言`zh`、CPU int8、4线程、beam size 5、单文件64MiB、300秒原音、110秒识别处理时限；模型冷启动计入处理时限，传输和登记校验开销另计。依赖FFmpeg，处理失败返回明确错误。`--source-dir`可从已有离线目录准备模型，不发起模型下载。

超级管理员在“模型服务”中登记类型`specialist`、适配功能`medical_transcription`，基础地址为同主机运行时的`http://127.0.0.1:8810`，密钥引用`AI_PROVIDER_LOCAL_SPEECH_API_KEY`或录入相同的加密保存密钥，模型标识使用`--describe`返回的实际值。请求超时设为120秒以覆盖110秒识别时限及部分传输开销。服务自身的语言、时长和资源配置属于部署参数，临床评审需记录其实际范围。

“检查本地语音服务”只对已保存配置执行鉴权`GET /capabilities`，不发录音、患者资料或模型推理；API接口为`POST /api/ai/admin/providers/{id}/speech-capabilities`，须有`expected_revision`，且仅超级管理员能调用。检查前后核对当前管理角色和配置版本，报告只显示已定义字段，不回显密钥、磁盘路径或任意服务响应。实际模型或请求超时不匹配时展示差异；“填写实际模型，待保存”只填写表单，保存与后续评审仍需分别执行。检查不会更改启用状态或登记临床验证。

该引擎执行声学转写，不把完整系统/任务Prompt、用户问题或病史作为`initial_prompt`或热词来补写发言；报告`prompt_handling: acoustic_only`。识别前核对实际模型支持的配置语言，拒绝英语专用模型把中文配置静默改为英语。保持原识别词句并逐段标记待核对，不区分说话人，统一`unknown`。若模型末尾估计超出原音，听音区间限定在实际范围，并在不确定说明中保留原估计值；`timestamp_policy: estimated_bounded_to_source`表示估计时间，不是人工对齐。VAD可能漏检；未返回片段不证明原音无人发言。真实术语、说话人和医疗质量评估仍未完成。

可用`Dockerfile.speech`单独构建运行镜像，主识别权重通过外部只读目录提供，不打包进应用镜像或Git；VAD资源随固定的识别依赖安装。镜像以非root用户运行，挂载目录需允许该运行UID读取；建议只读根文件系统与独立临时目录。镜像默认监听容器内8810端口，跨主机或容器调用需受信任HTTPS端点并加入原`AI_PROVIDER_ALLOWED_HOSTS`，可使用`--ssl-certfile`和`--ssl-keyfile`或已有TLS代理。容器内`127.0.0.1`指自身，不能直接当作另一个容器地址。没有修改现有Compose来默认启动或发布语音服务。

`scripts/smoke_local_speech.py`只生成固定的非临床英文合成语音及静音，检查WAV、WebM原字节传输、真实本地识别、完整输入报告与静音结果；它不接受实际患者录音。`tests/test_ai_local_speech_real.py`另用隔离数据库和合成患者，验证登记→排队→worker真实识别→冻结结果→授权读取，确认没有修改病历。默认测试不下载权重，该项需显式选择已准备的模型；两种检查均不构成中文、药名剂量、重叠发言或临床质量评估，也没有调用付费模型。

2026-10-20已实际构建该镜像，并在禁用网络、只读根目录、UID10001、4CPU/2GiB及独立临时目录的容器中通过3项检查：3.94秒WAV与WebM均识别出固定句子的四个核对关键词，0.25秒静音未返回片段。容器内153个Python源码文件与当时工作区哈希逐项一致；本地Python3.13环境和镜像Python3.12环境的依赖差异各自进入实际运行标识。详见[离线试跑记录](ai-speech-smoke.json)，其中只保存合成文本、实际版本和工程验证边界。

## 原始心电接入、候选复核与治理

编号37“心电辅助分析”使用明确的`ecg_asset_id`。门诊、住院病历行的“AI 心电复核”固定原患者及已记就诊，不把病历正文、检验文字、报告截图或外部URL当作原波形。工作台可以另选同患者的已登记记录。预览只提供原采样技术资料与独立引用；原头注释、原文件名、登记授权说明和无关病史不发送给模型。原采集时刻未知时保持未知，头文件时钟没有时区或核验依据时不升级为已确认采集时刻，也不按今天年龄推定采集人群。

### 当前支持的原文件

当前接收单段、单`.dat`文件的WFDB格式16（有符号16位小端、按导联交错），原`.hea`和`.dat`名称必须对应。每份1–16导联，采样率50–10000Hz，须显式声明样本数、导联、正增益、基线或ADC零值、物理单位、初值和校验和；不采用缺省增益或单位。识别标准导联及明确的MLII/MCL1/VX/VY/VZ标签，MLII不改成II。不接收212压缩、跨文件、多段、非零偏移/延迟或不同导联频率，不静默重采样、导联补全或截断。

原数字值`-32768`保留为缺失，不按0参与有效幅度或恒定值计算。校准按`(ADC－基线)/增益`及原单位换算mV，支持mV、uV/µV/μV和V；校验和按原数字样本核对。返回原初值声明和实际观察，不把恒定采样判为心搏停止或证明信号有效。全部导联只有缺失采样时仍可核查登记资料，但不能创建判读任务。格式校验、显示幅度与模型覆盖报告均不构成设备、信号质量或诊断验证。

格式解释参考[WFDB头文件规范](https://wfdb.io/spec/header-files.html)、[原采样格式规范](https://wfdb.io/spec/signal-files.html)及[官方Python读取接口](https://wfdb.readthedocs.io/en/latest/wfdb.html)。可选的`requirements-ecg-verification.txt`只安装格式对照库，不是诊断模型。`scripts/verify_ecg_wfdb.py`使用固定合成数字值、三种单位和不同基线，与WFDB 4.3.1对照：原导联顺序、缺失位置及mV换算一致。验证记录见[心电工程验证](ai-ecg-verification.json)，没有使用实际患者心电或评估疾病识别。

### 登记、读取及超管管理

`POST /api/ai/ecg-assets`以multipart提交`header`、`signal`、`patient_id`、可选`encounter_ref`、`authorization_confirmed`和至少5字的`authorization_note`；可选`recorded_at`须带时区，服务端统一UTC。先校验当前患者/原就诊权限，再解析文件，登记前再次核对当前角色、授权、配额和资料。原文件用独立私有目录保存，目录0700、文件0600，校验与登记不调用模型。不能将`AI_ECG_STORAGE_DIR`放在公开上传目录内。

| 项目 | 当前行为 |
| --- | --- |
| 使用角色 | 超级管理员、医生、科主任；检验技师另需当前有效、诊断用途的限时患者授权，普通检验单不自动授予原心电读取权 |
| 团队共享 | 当前具备原患者及原就诊诊疗权限的成员可读取他人登记原文件；撤回仅限登记人及超级管理员 |
| 文件额度 | 默认32MiB/份、300秒、512MiB/登记用户；`AI_ECG_MAX_BYTES`、`AI_ECG_MAX_DURATION_SECONDS`、`AI_ECG_USER_QUOTA_BYTES`可配置，撤回未清除的原文件仍占额度 |
| 原波形 | 鉴权`GET /api/ai/ecg-assets/{id}/window`，以原样本`start_sample`、`sample_count`及每导联点数`max_points`请求；保留原索引，概览保留极值并断开缺失区间 |
| 原文件导出 | 鉴权`GET /api/ai/ecg-assets/{id}/content?part=header\|signal\|pair`；pair为保留原文件名及原字节的ZIP，便于另行读取。原头注释可能含身份资料，仅明确操作时导出 |
| 撤回与清除 | 撤回和超管清除均要求`expected_revision`及原因；先持久化清除中状态，再删除当前原文件，失败可按新版本继续且保留首次清除说明 |
| 已有任务 | 原文件、当前诊疗关系、来源状态或版本变化会停止旧队列调用或拒收在途结果；普通用户不能继续读取失效来源的旧结果，超管仍可追查冻结快照 |

登记选项为`GET /api/ai/ecg-options`，患者目录为`GET /api/ai/ecg-assets`；超管目录和清除分别为`GET /api/ai/admin/ecg-assets`及`POST /api/ai/admin/ecg-assets/{id}/purge`。超管“心电原文件”页可查看原授权说明、按版本撤回及清除恢复，原文按纯文本显示。原波形和导出只在用户点击后读取，鉴权Token使用请求头，URL不含Token。关闭或切换来源会清理视图，迟到的上传、读取或定位回执不覆盖新患者和当前窗口。

API与worker必须共享`AI_ECG_STORAGE_DIR`；Compose已配置独立`ai_ecg_private`卷和相同额度，前端代理为成对上传保留最高128MiB及表单开销。清除删除当前存储原文件，任务文字、元数据及审计保留；撤回不能收回已发出的请求或已下载资料。

### 心电附件契约v3

该功能只接受`specialist`服务，不能回退到通用文本模型。网关发送multipart到已登记服务的`POST /tasks`：`task`为带完整系统/任务Prompt、原始技术资料、输入与引用的JSON字段，`waveform`为原始16位小端采样附件，固定文件名`signal.dat`。不发送磁盘路径或原头注释。服务必须按原导联数、原顺序、原采样率和校准参数解释附件，并核对所传文件哈希及其适用人群。

返回`schema_version: "3"`、准确的`feature_key: "ecg_analysis"`、登记的`model_version`、`applicable: true`和标准`result`，顶层另有`ecg_analysis`：

```json
{
  "asset_id": "请求中的原记录UUID",
  "content_hash": "请求中的64位组合哈希",
  "signal_hash": "请求中的64位原采样哈希",
  "time_basis": "relative_samples",
  "processing": {
    "instructions_digest": "完整instructions原文的SHA256",
    "input_sample_count": 1000,
    "input_sample_rate_hz": "500",
    "input_leads": ["I", "MLII"],
    "used_leads": ["I", "MLII"],
    "processed_original_sample_count": 1000,
    "complete_input": true,
    "missing_sample_handling": "masked",
    "preprocessing_notes": ["如实说明缺失掩码、滤波、重采样及适用性"]
  },
  "findings": [{
    "category": "other",
    "label": "待人工复核的候选",
    "description": "如实说明候选依据和局限",
    "leads": ["I"],
    "location": "sample_interval",
    "start_sample": 600,
    "end_sample_exclusive": 800,
    "score": 0.0,
    "score_kind": "model_score",
    "source_id": "请求提供的原心电引用"
  }]
}
```

该示例仅示意字段，标识、哈希、Prompt摘要、输入参数必须与实际请求一致。原采样计数和定位均为严格整数；`input_sample_rate_hz`保留原字符串，`input_leads`严格匹配原顺序，实际使用导联必须来自原输入。缺失样本必须报告`masked`及预处理说明，所用导联不能全部缺失。服务须报告完整原输入处理，不能把截短范围冒充全部；报告是服务声明，不是独立质量证明。定位使用原样本半开区间且不得越界，模型内部重采样后的索引必须还原。全记录候选用`location: "recording"`及空的起止值，不补写精确位置。最多100项，模型分数保留0和未提供的区别，不解释成患病概率。

结果可按候选定位到指定原导联，核查冻结元数据与原始波形，复制带导联、原区间、来源和原分数的待复核草稿；没有自动改写诊断、心电报告或签署。当前未集成或评估真实心电分类模型；85项心电后端测试和5项浏览器测试只验证合成波形、权限、传输协议及复核行为，临床启用仍需适用模型、真实数据、模型验证报告和人工评审。

## 验证命令

```bash
# fastapi_be
pytest -q tests/test_ai_catalog.py tests/test_ai_admin.py tests/test_ai_gateway.py tests/test_ai_context.py tests/test_ai_runtime.py tests/test_ai_migration.py tests/test_rbac_drift.py
pytest -q tests/test_ai_pathway_knowledge.py tests/test_ai_pathway_sources.py
pytest -q tests/test_ai_audio_files.py tests/test_ai_audio_assets.py tests/test_ai_audio_transcription.py tests/test_ai_response_fidelity.py tests/test_ai_knowledge_scope.py
pytest -q tests/test_ai_speech_model.py tests/test_ai_speech_processing.py tests/test_ai_speech_server.py tests/test_ai_speech_worker.py tests/test_ai_speech_probe.py
pytest -q tests/test_ai_ecg_files.py tests/test_ai_ecg_assets.py tests/test_ai_ecg_pipeline.py
# 可选格式互操作验证，安装requirements-ecg-verification.txt后运行，不下载心电模型
python scripts/verify_ecg_wfdb.py
# 可选真实模型检查；在已安装requirements-speech.txt的隔离环境运行
SPEECH_LANGUAGE=en python scripts/smoke_local_speech.py
HOIM_SPEECH_REAL_MODEL_DIR="$SPEECH_MODEL_DIR" pytest -q tests/test_ai_local_speech_real.py
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
