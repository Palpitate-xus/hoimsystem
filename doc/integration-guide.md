# LIS/PACS 对接指南

当前系统已提供厂商无关的入站桥接层，用于把 LIS 检验结果和 PACS 影像报告安全地写入本地申请单。它不代表已经完成某一家厂商的协议联调；实际部署仍需医院提供网络白名单、字段映射、证书/密钥和联调环境。

## 配置

在后端环境变量中配置独立密钥：

```dotenv
LIS_INTEGRATION_KEY=replace-with-a-random-secret
PACS_INTEGRATION_KEY=replace-with-a-random-secret
MEDICAL_INSURANCE_INTEGRATION_KEY=replace-with-a-random-secret
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

## 厂商联调前检查

- 确认厂商能够稳定提供本地申请单 ID 或完成外部单号映射。
- 明确 HL7、FHIR、厂商 REST 或消息队列的字段/编码转换规则。
- 在网关或防火墙配置来源 IP 白名单、TLS 和密钥轮换方案。
- 用重复消息、乱序消息、超时重试、错误单号和危急值样本完成验收。
- 由检验科/影像科确认外部结果进入院内审核，不得直接绕过审核对患者发布。
