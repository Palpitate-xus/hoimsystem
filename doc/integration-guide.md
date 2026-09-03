# LIS/PACS 对接指南

当前系统已提供厂商无关的入站桥接层，用于把 LIS 检验结果和 PACS 影像报告安全地写入本地申请单。它不代表已经完成某一家厂商的协议联调；实际部署仍需医院提供网络白名单、字段映射、证书/密钥和联调环境。

## 配置

在后端环境变量中配置独立密钥：

```dotenv
LIS_INTEGRATION_KEY=replace-with-a-random-secret
PACS_INTEGRATION_KEY=replace-with-a-random-secret
MEDICAL_INSURANCE_INTEGRATION_KEY=replace-with-a-random-secret
PAYMENT_INTEGRATION_KEY=replace-with-a-random-secret

# 需要向外部系统主动推送时配置；生产环境只允许 HTTPS
LIS_OUTBOUND_URL=https://lis.example.com/hoims/events
PACS_OUTBOUND_URL=https://pacs.example.com/hoims/events
MEDICAL_INSURANCE_OUTBOUND_URL=https://insurance.example.com/hoims/events
PAYMENT_OUTBOUND_URL=https://payment.example.com/hoims/events
```

调用时使用 `X-Integration-Key` 请求头。未配置密钥时接口返回 `503`，密钥不匹配返回 `401`。密钥不能写入前端代码、日志或版本库。

## LIS 结果回调

`POST /api/integration/lis/result`

```json
{
  "lab_order_id": "本地检验申请单 UUID",
  "external_order_id": "厂商申请单号",
  "sample_id": "样本号",
  "result": "结果文本或厂商映射后的结果",
  "abnormal_flag": 0
}
```

首次回调会将样本标记为已接收、生成待审核检验结果并记录同步时间；同一申请单再次回调会返回原结果并设置 `idempotent=true`，不会重复生成结果。危急值仍按本地规则识别。

### 危急值本地闭环

危急值结果创建后进入“待通知”状态。检验人员调用 `POST /api/labResult/critical/notify` 向开单医生发送院内消息；医生随后调用 `POST /api/labResult/critical/acknowledge` 确认接收，最后调用 `POST /api/labResult/critical/handle` 提交处理记录。三个操作均具备幂等保护，且会写入样本流转记录。处理状态只代表院内记录完成，不替代电话、短信或院内临床应急制度。

## PACS 报告回调

`POST /api/integration/pacs/report`

```json
{
  "imaging_order_id": "本地影像申请单 UUID",
  "external_order_id": "厂商检查号",
  "findings": "所见",
  "impression": "诊断意见",
  "viewer_url": "可选的受控阅片地址"
}
```

首次回调会生成或更新草稿报告，将影像申请置为“待审核”；重复回调幂等返回。已进入院内审核的报告不会被覆盖，避免外部重试造成医疗记录变更。

## 医保结算回调

收费端先调用 `/api/insurance/settlement/create`，并传入 `integration_mode: "external"` 创建“处理中”的本地记录；医保平台完成结算后调用 `POST /api/integration/insurance/settlement`：

```json
{
  "settlement_id": "本地结算记录 UUID",
  "external_settlement_id": "医保平台结算号",
  "status": 1,
  "total_amount": 1000,
  "covered_amount": 800,
  "self_amount": 200
}
```

系统会校验金额关系、绑定外部结算号并幂等更新状态；`status=1` 表示成功，`status=2` 表示失败。真实医保平台的目录编码、交易报文、签名证书和撤销/冲正规则仍需按平台规范联调。

## 出站事务发件箱

处方、检验申请、影像申请、收费/退款、发票、医保结算等关键业务会在同一个数据库事务中写入 `hoimsystem_integration_outbox`。业务提交成功而外部系统暂时不可用时，事件不会丢失；独立 `scheduler` 进程按批次投递：

- HTTP 成功后标记 `delivered`。
- 网络错误或非 2xx 响应按 30 秒起步的指数退避进入 `retry`，最长等待 1 小时。
- 达到 `INTEGRATION_MAX_ATTEMPTS` 后进入 `dead`，不再自动重试。
- 未配置对应出站 URL 时每 10 分钟延后，不影响本地业务事务。

出站请求包含 `Idempotency-Key`、`X-HOIM-Event-ID` 和 `X-HOIM-Event-Type`，并在配置密钥时使用 `Authorization: Bearer ...`。接收方必须按事件 ID 幂等处理，不能假设“只投递一次”。

管理员可在“系统管理 → 集成发件箱”查看状态、错误和最近 HTTP 状态，通过 `/api/integration/reconciliation` 对账，并对非成功事件执行人工重放。重放前应先确认外部系统是否已经处理，避免缺少幂等实现的接收方产生重复业务。

## 实时院内事件

浏览器通过 `GET /api/events/stream` 建立 SSE 长连接，`accesstoken` 放在请求头中，不放入查询字符串。事件包含受众角色/用户 ID，服务端在发送前再次过滤；Redis 用于跨 worker 广播并保留最近 500 条供断线续传。Nginx 必须关闭该路径的代理缓冲，配置见 [部署文档](deployDoc.md)。实时事件只用于界面刷新提示，不能替代数据库事务或外部系统发件箱。

## 厂商联调前检查

- 确认厂商能够稳定提供本地申请单 ID 或完成外部单号映射。
- 明确 HL7、FHIR、厂商 REST 或消息队列的字段/编码转换规则。
- 在网关或防火墙配置来源 IP 白名单、TLS 和密钥轮换方案。
- 用重复消息、乱序消息、超时重试、错误单号和危急值样本完成验收。
- 接收方按 `X-HOIM-Event-ID` 验证幂等；演练自动重试、死信、人工重放和业务对账。
- 由检验科/影像科确认外部结果进入院内审核，不得直接绕过审核对患者发布。
