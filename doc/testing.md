# 测试指南

测试分为业务回归、权限校验、模型协议联调、浏览器验收和并发压测。不同层的通过结果分别记录：模拟模型回复通过结构校验，并不等于真实模型推理或临床质量通过。

最近一次完整执行记录见 [2026-10-27 系统验证](validation/2026-10-27/README.md)。原始基线、失败、修复后的完整文件复验和性能测量分别保存，重复运行不累加为独立通过项。

## 后端

后端依赖包含 pytest、pytest-asyncio 和 httpx：

```bash
cd fastapi_be
python -m pip install --require-hashes -r requirements-build.lock
python -m pip install --require-hashes -r requirements-test.lock
python -m pytest tests --junitxml=pytest-results.xml
```

`tests/conftest.py` 在导入应用前固定使用内存 SQLite，并将请求依赖和中间件数据库会话指向同一个测试引擎。`seed_data` 创建合成业务记录和各角色用户；管理员身份通过测试夹具生成，不通过公开注册接口创建。

完整套件适合在独立进程中按文件分片，保持文件内测试及夹具完整。每片使用独立临时目录、数据库、私有文件目录和缓存。开始前保存收集清单，结束后核对节点没有重复或遗漏；不要在同一个进程中并发共享内存 SQLite 会话。

修改后的业务文件可先完整复验：

```bash
python -m pytest tests/test_business_flows.py tests/test_payment_integration.py
python -m pytest tests/test_all_protected_routes.py tests/test_openapi_schema.py
ruff check app tests
python scripts/generate_rbac_matrix.py --check
```

`test_all_protected_routes.py` 实际请求所有需登录的路由并验证 401，再为每个受角色限制的路由选择真实的禁止角色验证 403。它验证拒绝路径；业务成功流程仍由各模块测试负责。

## PostgreSQL 事务与并发

SQLite 回归用于业务规则和协议；并发结论使用独立 PostgreSQL 实例。以下测试显式要求本机专用库，未配置时真实 PostgreSQL 项会跳过：

```bash
export HOIM_TEST_POSTGRES_URL='postgresql+psycopg2://benchmark:benchmark-local-only@127.0.0.1:18427/hoimsystem_benchmark'
python -m pytest tests/test_postgresql_write_gates.py tests/test_ai_surgery_postgresql.py
export HOIM_TEST_POSTGRES_DDL_URL="$HOIM_TEST_POSTGRES_URL"
python -m pytest tests/test_sql_json.py tests/test_sql_text.py tests/test_sql_counts.py
```

测试在唯一临时 schema 或回滚事务中执行，并清理自身创建的对象。生产业务库不能用作压测目标。

真实 HTTP 并发验收使用 [concurrency_acceptance.py](../fastapi_benchmark/concurrency_acceptance.py)，检查响应和数据库最终状态：

```bash
BENCHMARK_DATABASE_URL='postgresql://benchmark:benchmark-local-only@127.0.0.1:18427/hoimsystem_benchmark' \
BENCHMARK_MODE=load \
python ../fastapi_benchmark/concurrency_acceptance.py \
  --host http://127.0.0.1:18127 --concurrency 20 --output /tmp/hoim-concurrency.json
```

输出文件必须不存在。每次使用新合成账号，验证账号能登录目标 API 后才执行业务写入。验收覆盖最后号源、重复预约和挂号、并行取消、支付、退费、床位占用、入院编号、发药及扫码给药。

分级负载使用 [隔离压测 Compose](../fastapi_benchmark/docker-compose.yml) 和 `locust_final.py`。小、中、大档分别包含 1,000 / 10,000 / 100,000 名患者及各 5,000 / 50,000 / 500,000 条处方、费用和病历历史。患者账号使用有界家庭，预约目标绑定实际授权令牌。每轮使用新令牌、实际有效的业务标识，HTTP 成功且业务 `code=200` 才计为成功。

记录实际数据库版本、镜像、源文件摘要、CPU/内存限额、worker 数、数据增量、测量时间窗、RPS、P50/P95/P99、失败率和资源采样。带思考时间的用户数不等于同时在途请求数；单轮短测也不能代替持续负载或生产容量规划。

## 文本模型模拟与重试

不连接真实模型时，使用 [本地模拟 LLM](../fastapi_benchmark/llm_simulator.md)。它提供真正的本机 HTTP 接口，支持 Chat Completions 和 Responses，回复明确标记为模拟，并能注入前几次 429、503 或断连。

模拟验证仍走应用原有的 Prompt、闭集结构、来源和引用校验。63 次网关调用与 63 条完整业务任务是不同层级；完整任务还要验证创建、claim、worker、结果读取、反馈和业务记录未被意外改写。

超级管理员在模型服务中配置“最多尝试次数（含首次）”。文本服务只对明确的临时 HTTP 错误和连接建立失败执行有限重试，总耗时服从原超时预算。鉴权、配置、结构、引用失败和已经开始交付的回复不自动重发；曾发生 HTTP 重试但无法证明完整用量时保留未知，不用末次 token 数冒充总量。

## 专用模型与可选运行时

普通回归不要求安装 Torch 或下载权重。数值和真实 CPU 推理测试在准备好对应依赖、固定权重后另行执行：

```bash
HOIM_IMAGING_REAL_MODEL=/path/to/verified-imaging-model \
python -m pytest tests/test_ai_imaging_preprocessing.py tests/test_ai_imaging_model.py

HOIM_IMAGING_REAL_MODEL_DIR=/path/to/verified-imaging-model \
python -m pytest tests/test_ai_local_imaging_real.py

HOIM_ECG_REAL_MODEL_DIR=/path/to/verified-ecg-model \
python -m pytest tests/test_ai_local_ecg_real.py

HOIM_SPEECH_REAL_MODEL_DIR=/path/to/verified-speech-model \
python -m pytest tests/test_ai_local_speech_real.py
```

仅用合成图像、波形或语音验证工程链路。推理执行成功不能作为疾病识别准确率、临床适用性或运营收益的证据。

## 前端

```bash
cd vue3-new-ui
npm ci --legacy-peer-deps
node --test tests/*.test.cjs
npm run audit
npm run build
npm run check:bundle
npx playwright test --list
```

浏览器验收分为实际业务 API 场景和独立页面夹具场景。前者需要独立测试数据库、合成账号及生产构建的静态代理；后者由各 spec 的 helper 启动自己的页面，仍需真实浏览器。

使用专门的验收配置设置 `fullyParallel: false`，避免同文件多个测试共享的编译服务器被并发关闭；保持重试为零，单独记录失败及复验。生产业务场景单 worker 运行，独立页面夹具可按文件适度并行。

部分完整页面夹具需要先编译三千余模块。`source-harness-setup.cjs` 只为编译型 `beforeAll` 设置独立准备预算；业务测试、动作和断言保持原预算。报告同时保留原准备超时、实际冷编译耗时和预算修正后的整文件结果。

修改 Prompt、公开界面文案或来源协议后，执行相应正式生成器并检查漂移。与后端摘要绑定的 Main/JWT 夹具应重新执行真实捕获流程，不能只替换 SHA 值来让测试通过。

## 结果归档

每次完整验证保存版本、收集清单、JUnit/Playwright JSON、覆盖率、失败与跳过原因、修复提交、整文件复验、真实服务及模拟服务的区别。发布报告附原始证据摘要和校验值；敏感配置、密钥、数据库文件及私有上传不进入版本管理。

## 持续负载入口

`soak` 数据配置包含 10 万患者、各 50 万条处方/费用/病历、50 万条审计日志，以及 20 名医生的完整周排班。预约池按家庭成员与不同医生日期组合生成，避免长测中目标耗尽后悄悄改变读写比例。

```bash
BENCHMARK_PROFILE=soak python fastapi_benchmark/run_load.py \
  --host http://127.0.0.1:51902 --users 100 --seconds 1800 \
  --output /tmp/hoim-soak-001
```

目标必须运行隔离压测入口，`/benchmark/info` 要匹配专用 PostgreSQL 数据库名、数据配置和负载模式。准备、登录、升压与预热不计入测量；请求在发出前标记所属时间窗，结束后限时排空在途请求。HTTP 和业务错误均保留，写入目标耗尽或请求未记账会判定结果无效；有请求失败时严格返回非零退出码。

本轮全量回归、容器审计、浏览器与长测结果见 [2026-10-28 优化验证](validation/2026-10-28-optimization.md)。
