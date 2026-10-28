# 本地演示

演示运行前端、API、PostgreSQL、Redis、AI worker、调度器和模拟模型服务，使用独立的 `hoim-preview` Compose 项目、数据库和数据卷。页面运行生产构建，通过 Nginx 同源代理访问 API。

## 启动

安装 Docker Compose、Python 3.10+（用于运行编排脚本）和 Node.js 24.x。后端在 Python 3.12.16 容器中运行。在仓库根目录执行：

```bash
npm --prefix vue3-new-ui ci --legacy-peer-deps
python scripts/local_preview.py start
```

首次启动自动生成 `.local-preview/preview.env` 中的独立随机密钥，完成迁移并创建演示账号和合成资料。配置文件不会提交到 Git。再次启动会保留已有账号、AI 管理配置及演示数据。

| 服务 | 地址 |
| --- | --- |
| 页面 | http://localhost:51891 |
| AI 工作台 | http://localhost:51891/#/ai/workbench |
| AI 管理中心 | http://localhost:51891/#/ai/manage |
| API 文档 | http://localhost:51800/docs |
| API 就绪检查 | http://localhost:51800/health/ready |

页面和 API 默认绑定 `0.0.0.0`，局域网内可使用 `http://开发机IP:51891` 直接访问。`0.0.0.0` 是监听地址，浏览器应填写实际 IP 或域名。数据库、Redis 和模拟模型不发布宿主机端口；需要仅本机访问时，可在 `.local-preview/preview.env` 中设置 `PREVIEW_BIND_ADDRESS=127.0.0.1`。

无法直接访问开发机网络时，也可通过 VS Code 转发 `51891`，或从自己的电脑建立 SSH 转发：

```bash
ssh -L 51891:127.0.0.1:51891 用户名@开发机
```

## 账号与查看顺序

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 超级管理员 | `super01` | `123456` |
| 医生 | `doctor1` | `doctor123` |
| 管理员 | `admin` | `admin123` |
| 患者 | `patient1` | `123456` |

其他岗位账号见项目 README。先以超级管理员登录，在管理中心查看模型、功能、默认 Prompt、权限和审计；再进入工作台选择以下任务：

| 任务 | 操作 |
| --- | --- |
| 患者全景摘要 | 选择“示例患者”，展开“联调与预览选项”，勾选“超级管理员预览”，提交问题 |
| 门诊病历草稿 | 选择“示例患者”并勾选预览，可从电子病历列表绑定已有记录进入；生成后核对正文与缺项 |
| 医院数据问答 | 选择日期范围并提问，可直接运行 |

患者和病历均为合成资料。初始化只配置这三项模型服务；其他能力在管理中心按各自的来源与服务要求配置。临床功能保持未验证、未启用，超级管理员通过现有预览流程查看结果；本地演示不会替代专业审核或更改临床启用条件。

模型回复来自仓库中的 [HTTP 模拟器](../fastapi_benchmark/llm_simulator.md)。模拟器在每个模型名称的前两次请求返回 503，客户端最多尝试三次，第三次可得到带明确模拟标记的合成回复。重试由原应用执行。重启模拟器会重置失败计数。此流程用于查看任务排队、有限重试、结果展示与人工反馈。

## 管理运行状态

```bash
python scripts/local_preview.py status
python scripts/local_preview.py logs
python scripts/local_preview.py stop
```

`stop` 移除该演示项目的容器与网络，保留数据卷。重新执行 `start` 可恢复演示。需要使用刚完成的前端构建时，可运行 `start --skip-frontend-build`。

如果镜像仓库不可访问，可在私有配置 `.local-preview/preview.env` 中设置 `PREVIEW_POSTGRES_IMAGE` 和 `PREVIEW_REDIS_IMAGE`，引用已核对版本的本地镜像 ID。PostgreSQL 需 14+，Redis 服务需兼容 Redis 协议；数据库镜像主版本须与该演示数据卷一致。

本机的启动、角色登录、模拟任务与重试验收见 [2026-10-28 演示验证](validation/2026-10-28-preview.md)。

本轮依赖升级、局域网 HTTP、浏览器和持续负载结果见 [2026-10-28 优化验证](validation/2026-10-28-optimization.md)。
