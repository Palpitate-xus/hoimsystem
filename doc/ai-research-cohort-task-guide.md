# 第74项专用科研待核问题任务：独立整合阶段

本文件说明本分支的专用任务接口和独立界面。项目、ACL、逐患者研究授权与病例来源治理见 [来源使用说明](ai-research-cohort-source-guide.md)。本阶段没有启用通用科研模型调度，也没有合入 MAIN、推送或部署。

## 明确来源与新任务

先明确研究项目及用途、有限患者集合、记录族和原记录日期范围，完成当前项目 ACL、逐患者授权记录的独立人工核查与技术治理，再捕获、审核并发布完整 Case。care/grant 只是访问依据，不能代替研究目的授权；技术发布不证明伦理审批、同意法律效力、研究资质或匿名。

`ResearchCohortAssistant` 复用已有 `ResearchCohortSourceInput`。用户必须明确选择并重新 GET 核对当前完整 Case；不会自动选第一项。任务只接受 `research_cohort_case_id` 和可选原问题，不接受 patient、encounter、其他功能的引用、SQL 或新的患者集合。原问题保留 Unicode 原字面量，最多2000码点、8000 UTF8字节，也会进入已授权模型请求，不自动匿名化。

本地 Case 有效不等于允许模型处理。未记录明确外部模型处理许可时，可以核对本地三值结果，但界面不提交模型任务。服务端在外发前和接受结果时，重新核当前用途、项目 ACL、每位患者研究授权、请求者角色与 token epoch、模型处理许可、Provider、配置和实际 Prompt 版本。超级管理员也没有临床正文或模型权限旁路。

公开来源预览展示本次 `research_source` 与原问题，不包含私有 Case、患者授权正文或 identity secret。实际请求还会绑定固定 System、当前完整 Task 版本、引用目录及输出 schema，并对完整请求再次核容量。预览本身不创建任务、不调用模型、不导出资料。

提交后先取得短排队回执，再按同一个规范任务 UUID GET 状态并比对完整来源锚；不会把另一条相同来源的任务当成本次回执。目录只提供技术元数据，查看历史任务不会自动选择它的来源或保留旧来源作为新模型任务输入。再次执行仍须明确核对当前来源。

## 独立读取与原始证据

专用路由在本分支实际 `app.main` 挂载，前缀为 `/api/ai/research-cohort/tasks`：

- POST：创建专用任务；输入只含上述 Case 引用和原问题。
- GET：受限分页的任务技术目录；普通用户只看自己的任务，超级管理员可显式技术审计。
- GET `/{run_id}`：短技术状态、冻结锚、实际可空用量与当前正文可读标志。
- POST `/{run_id}/cancel`：停止接收任务结果，不授予来源读取或新执行权限。
- GET `/{run_id}/parts/{source|scope|result|task}`：分别读取完整公开 Source、私有 Case、完整成功结果或冻结 Task 证明。

四个分件分别最多8MiB；原始 input/evidence/context-metadata 三个 TEXT 字符串各最多65535 UTF8字节，不把完整 Source、私有 Case 或完整结果重复塞入 Run.TEXT。Task 分件提供原字符串及 SHA、实际 Case 技术字段、完整冻结 Prompt/Provider/配置与来源 binding。客户端复用唯一来源 evaluator/HMAC 投影器重建完整 Case 和公开投影，并按原字符串 UTF8 核 SHA，不把 parse 后重新序列化的 JSON 称为原 TEXT。

默认 Prompt 明确为 `packaged_catalog`、版本0、数据库 Prompt FK 为 null，不自动写入管理员 Prompt 版本。已保存的自定义 Task 明确为 `database_version`、正版本号和实际不可变 Prompt FK；完整 Task 可以编辑为授权的新版本，固定 System 仍逐字附加并冻结。

每次临床分件读取仍核当前项目和逐患者权限。授权撤回或失效后，连超级管理员也不能从这些分件恢复临床原文、原问题或模型引文；只可保留受控技术状态、不透明哈希与实际用量。下一次请求发现失效、账户/token/角色变更、关闭原件或 KeepAlive 暂离时，界面清除旧正文；迟到网络与 SHA 响应不能恢复已关闭内容。

## 确定结果与模型评论

服务端保留全部明确患者的 `true/false/unknown` 原记录条件结果和整数计数，不把它们称为临床入组、疾病不存在、全院完整队列、发生率、因果或临床效果。日期、缺记录、矛盾父关联和未知值不由模型补齐。

模型最多提出128条部分待人工核查问题，也可以返回空问题集。每条问题必须精确引用本次公开来源已有字符串；临床证据问题必须引用实际证据 quote，条件声明不能冒充临床原记录。引用使用 Unicode 码点 `[start,end)`，保持 BOM、CRLF、emoji 与否定，不归一化；这里的坐标指公开证据字符串，不声称已披露完整原临床字段。

固定统计、摘要、limitations 和三值结果由服务器重建，模型只回填闭集问题草稿。界面将两者分开展示。没有任何自动纳排调整、SQL、入组、导出或临床业务写操作。

## 用量、停止与重复交付

创建、claim、dispatch、usage、accept 使用不同的具体 Audit 主键。dispatch 先以真实 FK 和 CAS 记录持久保留意图，事务提交并释放全部 SQL 连接后才发送 HTTP。相同 claim 重复交付只返回，不重放模型调用，也不替首个 worker 结束任务。

真正尚未调用的排队取消记已知0/0和 `model_call_attempted=false`。在途停止先记 pending；已付费回执保留实际输入/输出数量，单边未知仍为 null，不能补0。已保留 dispatch 后进程中断保持不确定且不自动付费重试。保留意图本身不证明物理模型调用已经发生。

## 尚未关闭的共享整合边界

本分支的专用 SQL/HTTPMock 队列、Main/JWT 接口和独立 Vue 界面已分别定向验证，不能据此宣称通用生产 worker 已接通。合入 MAIN 或激活第74项前，仍须由共享整合完成以下闭环：

- 当前旧 `claim_next_run` 会选择任意 queued AIRun，却按通用 payload 执行。必须先按真实研究 Artifact 分类，路由到专用 claim/execute，或明确排除专用队列。
- 旧通用 get/list/admin trace/cancel/feedback 不能绕过新的研究权限。实际隔离探针已确认：研究权限撤回后，旧管理 trace 仍可能200并回显冻结原问题，且通用读发生私有 Task TEXT SELECT；专用四分件则已拒绝。必须在私有 Task TEXT 前使用当前 opaque Artifact 与 Source 授权，并覆盖超级管理员和 marker/feature 损坏后的分类。
- 共享 catalog、默认 Task/运行输入模式、Provider/Prompt 管理与全量联合验收尚未作为本阶段成功结论。

这些边界是暂存分支的明确阻断，不能通过只挂新路由或仅有独立测试通过来忽略。旧失败、临时脚本错误和最终定向成功证据均保留在专用任务验证索引中。
