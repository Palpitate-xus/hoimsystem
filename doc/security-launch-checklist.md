# 生产上线安全基线核查单

> 本清单由 2026-08 安全审计生成，配合 `doc/security-baseline-checklist.md` 使用。
> 上线前逐项确认，任何一项未完成都不应发布到生产环境。

## 一、本次审计已修复（代码已改，随版本发布）

| # | 问题 | 修复 | 涉及文件 |
|---|------|------|---------|
| 1 | 未认证手术列表泄露全院患者身份证/诊断/排台 | 两个接口加 `require_roles(*CLINICAL_ROLES)` | `app/routers/surgery.py` |
| 2 | 患者角色可审批手术申请（越权） | 审批接口加临床角色限制 | `app/routers/surgery.py` |
| 3 | 耗材列表无认证 | 加药房角色限制 | `app/routers/consumable.py` |
| 4 | 体检记录/报告跨患者可读（IDOR） | patient 角色仅见本人 | `app/routers/exam.py` |
| 5 | 家庭成员绑定可劫持任意身份证号档案 | 已注册（permission=allow）患者禁止被他人绑定 | `app/routers/family_member.py` |
| 6 | 生命体征全院数据任意登录用户可读 | 限护理/管理角色 | `app/routers/vitalsign.py` |
| 7 | MDT/转诊/采购/分诊台列表缺角色限制 | 分别限临床/管理/导诊角色 | 对应 routers |
| 8 | 科研导出 doctor 角色可明文导出全库 PHI | 未脱敏导出仅限管理员 | `app/routers/research.py` |
| 9 | 分页无上限（page_size=-1 全表拖库） | paginate() 强制收敛 1..100 | `app/pagination.py` |
| 10 | 上传仅信任客户端 Content-Type，可传 HTML/SVG 实现存储 XSS | 扩展名白名单 + 魔数校验 + UUID 重命名 | `app/routers/upload.py` |
| 11 | `/uploads` 静态目录无鉴权暴露 | 移除 StaticFiles 挂载，统一走鉴权路由 + nosniff + attachment | `app/main.py` |
| 12 | CSV/Excel 公式注入（=WEBSERVICE 等） | 导出单元格以 = + - @ 开头前置单引号 | `research.py` / `data_import_export.py` |
| 13 | 备份等接口 str(e) 泄露内部信息 | 改为固定错误文案 | `app/routers/backup.py` |
| 14 | `/api/test` 任意回显 | 改为固定健康探测 | `app/routers/user.py` |
| 15 | 登录/注册不留审计痕迹（暴力破解无迹可查） | 审计中间件记录登录尝试（含用户名，不含密码） | `app/main.py` |
| 16 | 审计写入与请求会话竞态导致日志丢失 | 写入移至响应 BackgroundTask | `app/main.py` |
| 17 | 多 worker 各自生成 RSA 密钥导致登录随机失败 | 共享密钥文件/环境变量（TRANSPORT_RSA_PRIVATE_KEY_PEM） | `app/security.py` |
| 18 | 注册接口泄露"身份证号已注册"枚举探测点 | 统一模糊错误提示 | `app/routers/user.py` |
| 19 | Docker 镜像打包 dev 数据库（含 PHI + 密码哈希） | 新增 `.dockerignore` 排除 *.db/backups | `fastapi_be/.dockerignore`、`vue3-new-ui/.dockerignore` |
| 20 | nginx 无安全响应头 | CSP/nosniff/frame-options/referrer-policy/permissions-policy + 隐藏版本 | `vue3-new-ui/nginx.conf` |
| 21 | docker-compose 弱口令数据库、DB/后端口对外暴露 | POSTGRES_PASSWORD 必填、DB 仅内网、后端仅绑 127.0.0.1 | `docker-compose.yml` |
| 22 | 检验结果跨患者可读（IDOR 残留） | patient 角色仅见本人记录 | `app/routers/exam.py` |
| 23 | 护理巡视/医嘱执行/麻醉记录任意登录用户可读 | 限护理/临床角色 | `queue.py` / `inpatient_order.py` / `surgery.py` |
| 24 | 分诊记录任意账号可创建（注入临床数据） | 限导诊/护理角色 | `triage_desk.py` |
| 25 | 自助报到仅凭身份证号可枚举他人预约并代报到 | 双因子：身份证号 + 预留手机号后4位 | `checkin.py` + 前端 |
| 26 | JWT 无 exp 声明的令牌理论可接受 | decode 强制 require exp+sub | `app/dependencies.py` |
| 27 | 公式注入清洗未覆盖 tab/CR 变体 | 清洗字符集扩展 \t \r | `research.py` / `data_import_export.py` |
| 28 | viewer_url 可注入 javascript: 协议进前端 window.open | 两处入口强制 https:// | `imaging.py` / `integration.py` |
| 29 | logout 不吊销 token（24h 窗口内被窃取无法止损） | token_invalid_before 服务端吊销，logout/改密/管理员重置均触发 | `user.py` / `dependencies.py` |
| 30 | 登录失败锁定为进程内存态（4 worker 各自计数，重启清零） | 数据库持久化锁定表（LoginLockout） | `user.py` + 迁移 20260818 |
| 31 | RBAC 矩阵文档严重过期误导开发 | 脚本自动生成 560 个路由方法 + CI 漂移检测测试 | `scripts/generate_rbac_matrix.py` |
| 32 | 生产可写入公开的演示弱口令账号 | 生产环境阻止演示脚本，使用交互式强口令首管理员初始化 | `seed_default_accounts.py` / `bootstrap_admin.py` |
| 33 | Nginx 反代剥离 `/api` 且静态规则抢占 API 文件路径 | 保留 `/api` 前缀并让 API 前缀优先 | `vue3-new-ui/nginx.conf` |

## 二、上线前必须人工完成（无法代码代办）

### 🔴 阻断项（不完成不得上线）

- [ ] **安全初始化管理员**：确认生产未执行 `seed_default_accounts.py`；仅用 `bootstrap_admin.py` 交互创建首个强口令管理员
- [ ] **设置环境变量**：`SECRET_KEY`（`openssl rand -base64 48`）、`ALLOWED_ORIGINS`（精确域名，禁 `*`）、`POSTGRES_PASSWORD`
- [ ] **配置集成密钥**：`LIS/PACS/MEDICAL_INSURANCE/PAYMENT_INTEGRATION_KEY`（若启用对应回调）
- [ ] **多 worker 部署**：设置 `TRANSPORT_RSA_PRIVATE_KEY_PEM` 或确保 4 个 worker 共享密钥文件可写路径
- [ ] **HTTPS**：在 nginx 前配置 TLS 证书（443 + 80 跳转），JWT/密码否则明文传输
- [ ] **生产库禁用 SQLite**：`DATABASE_URL` 指向 PostgreSQL；SQLite 备份/恢复接口在生产自动返回 501
- [ ] **删除/隔离开发数据**：确认镜像内无 test.db/backups（已由 .dockerignore 处理，需在 CI 验证）

### 🟡 强烈建议（上线一周内完成）

- [ ] 数据库定期备份异地化（backup.py 仅 SQLite 且本地盘）
- [ ] 登录失败锁定策略接入 IP 级（当前 用户名+IP 5 次/5 分钟，已持久化跨 worker；如需纯 IP 封禁需在网关做）
- [ ] JWT 有效期从 24h 收紧至 2-4h（`user.py create_access_token`）；吊销机制已上线，短期化后体验损失更小
- [ ] 集成回调升级为 HMAC 请求签名（时间戳+nonce 防重放），密钥版本化支持轮换（需与 LIS/PACS 厂商协商）
- [ ] 慢查询/大表监控：核心报表已改 SQL 聚合，仍需在生产启用 `pg_stat_statements` 并按真实计划持续优化
- [ ] 密码策略升级：最短 6 位→8 位+复杂度；移除 legacy 明文哈希兼容（迁移完成后删 `verify_password` 的 fallback 分支）

### 🟢 已知可接受风险（记录在案）

- token 存 localStorage（XSS 可窃取）：前端已有 sanitizeHtml，且无第三方脚本注入面；如需更强可改 HttpOnly Cookie + CSRF token
- LIKE 通配符未转义（%/_ 注入通配语义，非 SQL 注入）：影响为查询放大，优先级低

## 三、验证方式

```bash
# 1. 跑安全相关测试
cd fastapi_be && python3 -m pytest tests/ -q

# 1b. RBAC 矩阵漂移检测（路由鉴权变更后需重新生成矩阵）
cd fastapi_be && python3 scripts/generate_rbac_matrix.py --check

# 2. 验证未认证访问被拒
curl -i http://localhost:8000/api/surgeryApplication/getList        # 应 401/403
curl -i http://localhost:8000/api/consumable/getList                # 应 401/403
curl -i http://localhost:8000/uploads/reports/anything.pdf          # 应 404（无此路由）

# 2b. 验证 token 吊销（logout 后旧 token 应 401）
TOKEN=$(curl -s -X POST http://localhost:8000/api/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<新密码>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["accesstoken"])')
curl -s -X POST http://localhost:8000/api/logout -H "accesstoken: $TOKEN"
curl -i http://localhost:8000/api/doctorManagement/getList -H "accesstoken: $TOKEN"   # 应 401

# 3. 验证镜像无数据库文件
docker build -t hoim-backend ./fastapi_be
docker run --rm hoim-backend find /app -name "*.db" | wc -l         # 应为 0

# 4. 验证多 worker 登录稳定（4 worker 下连续登录 20 次）
for i in $(seq 1 20); do curl -s -X POST http://localhost:8000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<新密码>"}' | grep -c success; done
```
