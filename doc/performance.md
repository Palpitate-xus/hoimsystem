# 性能优化指南

> 本文档汇总后端、前端、数据库的性能优化方法，按"识别 → 测量 → 优化"流程组织。

---

## 一、性能指标

### 1.1 关键指标

| 维度 | 指标 | 目标 |
|:----:|:----|:----:|
| 后端 API | P50 响应时间 | < 50ms |
| 后端 API | P95 响应时间 | < 200ms |
| 后端 API | P99 响应时间 | < 500ms |
| 后端 API | 错误率 | < 0.1% |
| 后端 API | 单实例 QPS | ≥ 1000 |
| 数据库 | 慢查询（>100ms） | < 1% |
| 前端 | 首屏加载（FCP） | < 1.5s |
| 前端 | 交互响应（INP） | < 200ms |
| 前端 | bundle 大小 | < 1MB（gzip 后） |

---

## 二、后端性能优化

### 2.1 识别瓶颈

#### 启用 SQL 日志

```python
# 临时打开（仅调试用）
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

#### 用 cProfile

```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# ... 业务代码 ...

profiler.disable()
stats = pstats.Stats(profiler).sort_stats('cumulative')
stats.print_stats(30)
```

#### 用 APM 工具

生产环境推荐：
- [py-spy](https://github.com/benfred/py-spy) — 采样式 profiler，无侵入
- [OpenTelemetry](https://opentelemetry.io/) — 分布式追踪
- [Sentry](https://sentry.io/) — 错误 + 性能监控

### 2.2 数据库查询优化

#### N+1 查询问题

❌ **典型反模式**：
```python
patients = db.query(Patient).all()  # 1 次查询
for p in patients:
    print(p.doctor.name)  # 每次都查一次 doctor，共 N 次
```

✅ **修复**：用 `joinedload` 预加载
```python
from sqlalchemy.orm import joinedload

patients = db.query(Patient).options(joinedload(Patient.doctor)).all()
```

#### 加索引

```python
# models.py
class Patient(Base):
    patient_id = Column(Integer, primary_key=True)
    identity = Column(String(18), index=True)        # 单列索引
    phone = Column(String(20), index=True)

    __table_args__ = (
        Index('idx_name_phone', 'name', 'phone'),    # 联合索引
    )
```

**何时加索引：**
- WHERE 子句中频繁出现的字段
- ORDER BY 字段
- JOIN 字段（外键）

**何时不加：**
- 唯一值很少的字段（如 `status`，只有 0-4 几个值）
- 写多读少的表（索引拖慢写入）

#### 避免大表全扫描

```python
# ❌ 不好：可能扫描百万行
patients = db.query(Patient).all()

# ✅ 加分页
page_size = 20
patients = db.query(Patient).offset(0).limit(page_size).all()

# ✅ 用过滤条件
patients = db.query(Patient).filter(Patient.create_time > yesterday).limit(100).all()
```

#### 只查需要的字段

```python
# ❌ 查全部字段
patients = db.query(Patient).all()

# ✅ 只查需要的
from sqlalchemy import select
result = db.execute(
    select(Patient.patient_id, Patient.name).where(...)
).all()
```

### 2.3 接口层优化

#### 分页参数

所有列表接口都应支持分页：
```python
@router.get("/list")
def list_xxx(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    query = db.query(Xxx)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"code": 200, "data": {"list": items, "total": total}}
```

#### 避免重复计算

```python
# ❌ 每次请求都重新计算
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    today_count = db.query(...).filter(...).count()  # 慢查询
    return {"count": today_count}

# ✅ 加缓存
from functools import lru_cache

@lru_cache(maxsize=1)
def get_today_count_cached():
    # ... 1 分钟缓存
    pass
```

更复杂的缓存用 Redis（项目目前未引入）。

### 2.4 异步与并发

#### 同步 → 异步

```python
# 同步（阻塞）
@router.get("/data")
def get_data():
    result = requests.get("https://api.example.com").json()  # 阻塞
    return result

# 异步
@router.get("/data")
async def get_data():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com")
    return response.json()
```

#### 并发外部调用

```python
import asyncio
import httpx

async def get_combined_data():
    async with httpx.AsyncClient() as client:
        # 并发，而不是串行
        results = await asyncio.gather(
            client.get("https://api1.com"),
            client.get("https://api2.com"),
        )
    return [r.json() for r in results]
```

### 2.5 生产部署优化

#### 使用 Gunicorn + Uvicorn

```bash
# 工作进程数 = (CPU 核数 × 2) + 1
gunicorn app.main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  --worker-connections 1000 \
  --bind 0.0.0.0:8000
```

#### 启用 Gzip 压缩

```python
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

#### 数据库连接池

```python
# database.py
engine = create_engine(
    DATABASE_URL,
    pool_size=20,           # 连接池大小
    max_overflow=10,        # 超额连接数
    pool_pre_ping=True,     # 自动检测断连
    pool_recycle=3600,      # 1小时后回收连接
)
```

---

## 三、前端性能优化

### 3.1 识别瓶颈

#### Chrome DevTools

- **Lighthouse**：综合评分，找出问题
- **Performance** 面板：分析具体页面加载
- **Network** 面板：看请求耗时和大小
- **Coverage** 面板：找未使用的代码

#### 关键指标

```javascript
// 在浏览器控制台运行
console.log({
  FCP: performance.getEntriesByName('first-contentful-paint')[0]?.startTime,
  LCP: performance.getEntriesByType('largest-contentful-paint').slice(-1)[0]?.startTime,
  TTI: performance.timing.domInteractive - performance.timing.navigationStart,
});
```

### 3.2 减小 bundle 体积

#### 路由懒加载（已开启）

```javascript
// router/index.js
{
  path: 'patient',
  component: () => import('@/views/patient/index.vue'),  // 懒加载
}
```

#### 按需引入

```javascript
// ❌ 全量引入
import _ from 'lodash';

// ✅ 按需
import debounce from 'lodash/debounce';

// ✅ 用原生
const debounce = (fn, delay) => { /* 简易实现 */ };
```

#### 分析 bundle

```bash
# 安装分析工具
npm install -D webpack-bundle-analyzer

# 修改 rspack.config.js 添加 analyzer
```

### 3.3 优化首屏

#### 启用 Gzip（Nginx）

```nginx
gzip on;
gzip_types text/plain application/javascript application/json text/css text/xml;
gzip_min_length 1024;
gzip_comp_level 6;
```

#### 静态资源 CDN

```html
<!-- 把 element-plus、vue 等放 CDN -->
<link rel="stylesheet" href="https://unpkg.com/element-plus/dist/index.css" />
<script src="https://unpkg.com/vue@3.4/dist/vue.global.prod.js"></script>
```

#### 预加载关键资源

```html
<link rel="preload" href="/api/login" as="fetch" />
```

### 3.4 列表渲染优化

#### 虚拟滚动（大列表）

```vue
<!-- Element Plus el-table-v2 支持虚拟滚动 -->
<el-table-v2
  :data="hugeList"
  :columns="columns"
  :height="600"
/>
```

#### 分页 + 服务端排序

不要一次性渲染 10000 行，用分页。

#### v-show 而非 v-if（频繁切换）

```vue
<!-- 频繁切换用 v-show -->
<el-dialog v-show="visible" />

<!-- 偶尔显示用 v-if -->
<el-dialog v-if="visible" />
```

### 3.5 图片优化

```vue
<!-- 加 loading="lazy" -->
<img src="..." loading="lazy" />

<!-- 用现代格式 -->
<picture>
  <source srcset="image.webp" type="image/webp" />
  <img src="image.jpg" />
</picture>
```

---

## 四、数据库优化

### 4.1 慢查询定位

#### PostgreSQL

```sql
-- 开启慢查询日志
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- 1秒以上
SELECT pg_reload_conf();

-- 查询当前活跃 SQL
SELECT pid, query, state, age(now(), query_start) AS duration
FROM pg_stat_activity
WHERE state = 'active'
ORDER BY duration DESC;

-- 查询慢 SQL（需要 pg_stat_statements 扩展）
SELECT query, calls, total_exec_time, mean_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

#### EXPLAIN ANALYZE

```sql
EXPLAIN ANALYZE
SELECT * FROM hoimsystem_patient WHERE name LIKE '%张%';

-- 看输出：
-- Seq Scan = 全表扫描 ⚠️
-- Index Scan = 用了索引 ✅
-- Nested Loop = 嵌套循环（可能很慢）
-- Hash Join = 哈希连接（数据量大时好）
```

### 4.2 索引优化

#### 查找缺失的索引

```sql
-- PostgreSQL: 找出未被索引的外键
SELECT
  tc.table_schema, tc.table_name, kc.column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kc
  ON tc.constraint_name = kc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND NOT EXISTS (
    SELECT 1 FROM pg_indexes pi
    WHERE pi.tablename = tc.table_name
      AND pi.indexdef LIKE '%' || kc.column_name || '%'
  );
```

#### 删除冗余索引

```sql
-- 找出未使用的索引
SELECT schemaname, tablename, indexname, idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0;
```

### 4.3 表设计优化

#### 分区表（大表）

```sql
-- 按月分区
CREATE TABLE hoimsystem_operation_log (
  log_id BIGSERIAL,
  create_time TIMESTAMP NOT NULL,
  ...
) PARTITION BY RANGE (create_time);

CREATE TABLE hoimsystem_operation_log_202605 PARTITION OF hoimsystem_operation_log
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
```

#### 冷热数据分离

将历史数据归档到独立表：
```sql
CREATE TABLE hoimsystem_appointment_archive AS
SELECT * FROM hoimsystem_appointment WHERE create_time < '2025-01-01';

DELETE FROM hoimsystem_appointment WHERE create_time < '2025-01-01';
```

---

## 五、缓存策略

### 5.1 何时引入 Redis

当前项目**未引入** Redis，但以下场景值得考虑：

- 接口 QPS > 100 但数据变化少（如字典、配置）
- 复杂计算结果（如报表）
- 分布式 session（如多实例部署）

### 5.2 缓存示例（未实现）

```python
import redis
import json

redis_client = redis.Redis(host='localhost', port=6379, db=0)

@router.get("/config/getList")
def get_config_list(db: Session = Depends(get_db)):
    cache_key = "config:list"
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    data = db.query(Config).all()
    result = {"code": 200, "data": [c.to_dict() for c in data]}

    # 缓存 5 分钟
    redis_client.setex(cache_key, 300, json.dumps(result))
    return result
```

### 5.3 缓存失效

更新数据时主动失效：
```python
@router.post("/config/update")
def update_config(req: ConfigUpdateRequest, db: Session = Depends(get_db)):
    # ... 更新数据库
    redis_client.delete("config:list")  # 失效缓存
    return {"code": 200}
```

---

## 六、压力测试

### 6.1 使用 wrk

```bash
# 安装
brew install wrk          # Mac
apt install wrk           # Ubuntu

# 测试
wrk -t12 -c400 -d30s http://localhost:8000/

# -t12: 12 个线程
# -c400: 400 个并发连接
# -d30s: 持续 30 秒
```

### 6.2 使用 Locust

```python
# locustfile.py
from locust import HttpUser, task, between

class APIUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        response = self.client.post("/api/login",
            json={"username": "admin", "password": "admin123"})
        self.token = response.json()["data"]["accesstoken"]

    @task
    def list_patients(self):
        self.client.get("/api/patientManagement/getList",
            headers={"accesstoken": self.token})
```

```bash
pip install locust
locust -f locustfile.py --host http://localhost:8000
# 访问 http://localhost:8089 配置测试
```

---

## 七、当前性能基线

> 在 SQLite + 本地开发机器测试（CPU: i7, 内存 16GB）

| 指标 | 数值 |
|:----:|:----:|
| 简单 CRUD API（如 /patientManagement/getList） | P50 < 20ms |
| 复杂关联查询（如 /charge/getList） | P50 50-100ms |
| 报表统计 | P50 200-500ms |
| 单实例吞吐 | ~3000 QPS |

> 生产环境（PostgreSQL）性能会显著高于此。

---

## 八、性能优化清单

发现性能问题时按顺序排查：

- [ ] **测量**：先用 profiling 工具定位瓶颈，不要瞎猜
- [ ] **数据库**：是否有慢查询？索引是否合理？是否 N+1？
- [ ] **接口**：是否分页？是否只查需要的字段？
- [ ] **缓存**：高频查询是否可缓存？
- [ ] **前端**：bundle 是否过大？是否懒加载？
- [ ] **网络**：是否启用 gzip？资源是否走 CDN？

---

## 九、参考资料

- [FastAPI Performance](https://fastapi.tiangolo.com/deployment/concepts/)
- [SQLAlchemy Performance](https://docs.sqlalchemy.org/en/20/faq/performance.html)
- [Vue 3 Performance](https://vuejs.org/guide/best-practices/performance.html)
- [Web Vitals](https://web.dev/vitals/)
