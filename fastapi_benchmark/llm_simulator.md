# 本地模拟 LLM

`llm_simulator.py` 用于合成资料的 Chat Completions / Responses HTTP 联调。它没有加载模型；回复、健康接口与响应头均带模拟标识，不能作为临床质量或真实推理能力的验证结果。服务不会自动接入应用或修改管理员配置。

先创建独立测试密钥文件，再启动仅监听本机的服务：

```bash
python -c 'from pathlib import Path; import secrets; p=Path("/tmp/hoim-simulator-test.key"); p.write_text(secrets.token_urlsafe(32)); p.chmod(0o600)'
python fastapi_benchmark/llm_simulator.py --port 18953 --key-file /tmp/hoim-simulator-test.key
```

在隔离测试数据库中配置服务地址 `http://127.0.0.1:18953/v1`，显式使用该测试密钥。模型名称必须为 `hoim-simulator:<feature_key>`，例如 `hoim-simulator:patient_summary`、`hoim-simulator:outpatient_note`。共享任务返回带引用的保守结构；专用任务根据完整公开来源生成相应闭集草稿，原应用仍负责权限、来源与引用校验。仅向此服务发送合成资料。

通过启动参数注入每个模型名称的前两次失败，以验证客户端有限重试：

```bash
python fastapi_benchmark/llm_simulator.py --port 18954 --key-file /tmp/hoim-simulator-test.key --fail-first 2 --failure 503
```

`--failure` 支持 `429`、`503`、`disconnect`，`--fail-first` 范围为 0–10。计数按模型名称独立维护；重启服务会清零。`GET /_simulator/stats` 使用同一 Bearer 测试密钥认证，返回调用、注入失败与成功次数，不返回请求内容或凭据。`GET /health/ready` 明确返回 `simulated: true`、`model_inference: false`。模拟响应的 usage 为零，表示没有进行模型推理，不代表真实服务的计费或 token 测量。

服务收到请求后断连属于交付状态不确定的失败；客户端是否重试应遵循其生产重试策略，不能把它等同为连接尚未建立。模拟器本身不进行请求重试，也不执行任何业务写入。
