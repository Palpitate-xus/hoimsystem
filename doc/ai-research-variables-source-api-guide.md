# 第76项来源 API：独立接线阶段

本阶段提供变量字典与完整批次的专用来源接口。路由前缀为 `/api/ai/research-variables`，已在隔离测试中挂到真实 `app.main` 并使用 JWT 和合成 SQLite 验证；产品 Main、共享目录、模型执行和默认启用尚未接入。此前私有 MySQL 来源服务验证与本次 HTTP 验证分别记录，不把二者拼成生产全链结论。

普通来源操作角色为 super_admin、admin、director、doctor、pharmacist。角色本身不授予研究权限；任何字典或批次正文读取前，都重新核对当前项目三锚、明确 `research_variable_extraction` 用途、项目 ACL 和项目全部患者的研究授权。批次即使只选项目部分患者，当前版本也保守要求全部 Scope 患者授权；超级管理员不能绕过撤权读取正文。care/grant 只是访问依据，不等于研究目的、伦理审批、研究资质或模型处理许可。

## 明确字典和批次

先依据已授权项目创建完整变量字典。每个变量明确原记录族、真实字段、原字段类型及窗口；不自动推断单位、改写否定、选最新原件或推导缺失原因。独立定义核查与超级管理员技术发布是不同操作；技术发布不能代填独立核查，也不证明变量科学有效性。

字典 API 支持创建、独立定义核查、发布或驳回、撤销，以及短详情。批次 API 支持受控只读 preview、创建、技术发布或驳回、撤销，以及短详情。请求全部使用实际 `DictionaryCreate/DefinitionReview/BatchCapture/BatchCreate/SourceReview/SourceRevoke` 闭集，拒绝额外患者、模型或其他任务参数。

所有写操作只返回短 ACK，明确 `fresh_parts_required=true`。ACK、目录和短详情没有 `eligible` 字段，不能用作完整来源或新任务选择成功的证明。不得自动发布、自动选第一项或把技术状态视为临床资格。

## 分件与当前性

字典和批次的目录均须显式项目三锚；分页只展示技术引用，不代表截断后完整来源。目录最多每页100项，返回 `items/page/size/total`，不读取变量字典、批次或自由审核备注的 TEXT。短详情同样没有正文。

完整读取分别使用：

- 字典 `GET /dictionaries/{id}/parts/definition`：完整原字典证明，单独移除 `parent_binding`。
- 字典 `GET /dictionaries/{id}/parts/scope`：完整原 `parent_binding={scope:原项目证明}`。
- 批次 `GET /batches/{id}/parts/source`：完整服务端重建的公开文字来源。
- 批次 `GET /batches/{id}/parts/snapshot`：完整私有快照与不重复 Source 的薄证明。

每份分件连同 HTTP 回执各限8MiB，超限整件拒绝，不能裁字段、授权或原文。实际测试的已发布完整批次旧聚合包为9,356,680字节；新 Source 与 Snapshot HTTP 回执分别为4,672,728和4,686,650字节。它们是同一真实合成批次的完整分件，不是放宽单件容量。

每份分件都携带实际短 metadata 和当前验证结果。组合前须核对全部 metadata 相同，包括项目、字典、内容及投影 SHA、版本、签署状态、时钟和具体 `last_event_id`。独立定义核查在 revision 仍为1时就改变具体回执主键，不能只比较 revision。旧分件与撤销后新分件不能组成 Ready；两份分件均须重新核验且当前 eligible。预览或历史旧哈希不取代服务端下一次当前授权。

Snapshot/Source 内容 SHA 基于完整 canonical JSON 的原 UTF8 字节；导出证据中的整个 HTTP 原回执 SHA 是额外传输证据，不能混用。原 BOM、CRLF、emoji、NULL、零、未知时钟和原记录状态不归一化。

每批次32字节 HMAC 私钥保留在院内数据库，不通过 API、公开来源或模型请求外发。服务端使用真实私钥重新验证完整私有快照与公开标识映射。客户端可以核整件 SHA、同 metadata、项目和字典绑定、原文字面及码点引用，不能声称仅凭私钥哈希独立重算完整 HMAC 投影。隐私最小化不等于匿名，实际原文仍可能包含标识信息。

## 撤权与技术目录

`GET /technical/{dictionaries|batches}` 及对应短详情仅供当前超级管理员，仍核本次请求已加载角色和 token epoch。这里只返回技术标识、状态、版本、时钟、实际主键和哈希；original 与审核备注始终为 null，不包含患者集合或 eligibility。

来源授权撤回后，包括超级管理员在内的普通正文路径返回403，并在字典/批次 TEXT SELECT 前拒绝。技术目录仍可提供不透明引用，但不能恢复患者正文。正常路径不接受 `audit_only` 来改变这个边界。

本阶段没有科研模型任务、自动 SQL、患者扩展、医学归一化、数据导出或业务记录写入。完整后续接线仍须独立核验，不把本阶段定向测试称作完整生产验收。
