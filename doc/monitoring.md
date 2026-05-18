# 监控与运维指南

> 本文档说明生产环境如何监控系统健康状态、排查问题、应对告警。

---

## 一、监控分层

```
┌────────────────────────────────────┐
│      业务监控（应用层）              │
│  - 关键流程成功率                    │
│  - 用户行为统计                      │
│  - 错误日志                          │
├────────────────────────────────────┤
│      应用监控（服务层）              │
│  - API 响应时间                      │
│  - QPS / 并发数                      │
│  - 异常率                            │
├────────────────────────────────────┤
│      基础设施监控（系统层）          │
│  - CPU / 内存 / 磁盘                 │
│  - 网络流量                          │
│  - 数据库连接池                      │
└────────────────────────────────────┘
```

---

## 二、健康检查

### 2.1 后端健康检查端点

```python
# 在 app/main.py 中添加（可选实现）
@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(503, detail=str(e))


@app.get("/health/detailed")
async def detailed_health(db: Session = Depends(get_db)):
    return {
        "status": "healthy",
        "version": "1.1.0",
        "uptime_seconds": int(time.time() - START_TIME),
        "database": {
            "connected": True,
            "user_count": db.query(User).count(),
        },
        "memory_mb": psutil.Process().memory_info().rss / 1024 / 1024,
    }
```

### 2.2 用 curl 检查

```bash
# 简单检查
curl -f http://localhost:8000/health || echo "DOWN"

# 详细检查
curl -s http://localhost:8000/health/detailed | python -m json.tool
```

### 2.3 Systemd 自动重启

```ini
# /etc/systemd/system/hoimsystem.service
[Service]
ExecStart=...
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=3
```

---

## 三、日志管理

### 3.1 日志分类

| 类型 | 内容 | 位置 |
|:----:|:----|:----|
| **应用日志** | INFO/WARNING/ERROR | stdout / `/var/log/hoimsystem/app.log` |
| **访问日志** | HTTP 请求记录 | Nginx access.log |
| **错误日志** | HTTP 5xx 错误 | Nginx error.log |
| **操作日志** | 业务操作审计 | `hoimsystem_operation_log` 表 |
| **数据库日志** | SQL 执行 | PostgreSQL log |

### 3.2 配置应用日志

```python
# fastapi_be/app/main.py
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),  # stdout
        RotatingFileHandler(
            '/var/log/hoimsystem/app.log',
            maxBytes=100 * 1024 * 1024,  # 100MB
            backupCount=10,
        ),
    ],
)
```

### 3.3 关键日志规范

```python
import logging
logger = logging.getLogger(__name__)

# ✅ 业务操作日志
logger.info(f"User {user_id} created prescription {pres_id}")

# ✅ 异常日志（含上下文）
try:
    ...
except Exception as e:
    logger.exception(f"Failed to process appointment {appt_id}")  # 自动带堆栈

# ✅ 性能日志
start = time.time()
result = expensive_operation()
logger.info(f"expensive_operation took {time.time() - start:.2f}s")

# ❌ 不要 log 敏感信息
logger.info(f"User {username} password is {password}")  # ❌ 绝对禁止
```

### 3.4 日志轮转

```bash
# /etc/logrotate.d/hoimsystem
/var/log/hoimsystem/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload hoimsystem || true
    endscript
}
```

---

## 四、Nginx 日志

### 4.1 自定义日志格式

```nginx
# /etc/nginx/nginx.conf
log_format main_json escape=json '{'
    '"time":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"method":"$request_method",'
    '"uri":"$request_uri",'
    '"status":$status,'
    '"bytes_sent":$bytes_sent,'
    '"request_time":$request_time,'
    '"upstream_response_time":"$upstream_response_time",'
    '"user_agent":"$http_user_agent"'
'}';

access_log /var/log/nginx/hoimsystem-access.log main_json;
```

### 4.2 实时监控访问

```bash
# 实时查看
tail -f /var/log/nginx/hoimsystem-access.log

# 统计慢请求
awk -F'"request_time":' '{print $2}' /var/log/nginx/hoimsystem-access.log \
  | awk -F',' '{print $1}' | sort -n | tail -20

# 统计 5xx 错误
grep '"status":5' /var/log/nginx/hoimsystem-access.log | wc -l

# 统计访问量 TOP URI
awk -F'"uri":"' '{print $2}' /var/log/nginx/hoimsystem-access.log \
  | awk -F'"' '{print $1}' | sort | uniq -c | sort -rn | head -20
```

---

## 五、错误监控

### 5.1 Sentry 接入（推荐）

```bash
pip install sentry-sdk[fastapi]
```

```python
# app/main.py
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    integrations=[FastApiIntegration()],
    traces_sample_rate=0.1,        # 10% 性能采样
    profiles_sample_rate=0.1,
    environment=os.getenv("ENV", "production"),
)
```

Sentry 自动捕获：
- 未处理异常
- HTTP 错误
- 慢请求
- 数据库错误

### 5.2 邮件告警（轻量方案）

```python
# app/main.py
from app.utils.alert import send_alert_email

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    error_msg = f"{request.url.path}: {exc}"
    send_alert_email("【告警】HIS-OP 异常", error_msg)
    return JSONResponse({"code": 500, "msg": "系统异常"}, status_code=500)
```

---

## 六、性能监控

### 6.1 Prometheus + Grafana（推荐）

#### 暴露指标

```bash
pip install prometheus-fastapi-instrumentator
```

```python
from prometheus_fastapi_instrumentator import Instrumentator

Instrumentator().instrument(app).expose(app)
# 自动暴露 /metrics
```

#### Prometheus 配置

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'hoimsystem-backend'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

#### Grafana 看板

导入推荐看板：
- [FastAPI Dashboard](https://grafana.com/grafana/dashboards/14282-fastapi-observability/)
- 关键指标：QPS、P50/P95/P99、错误率、请求时长分布

### 6.2 Node Exporter（系统监控）

```bash
# 安装
wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
tar xzf node_exporter-*.tar.gz
./node_exporter &

# Prometheus 配置增加
- job_name: 'node'
  static_configs:
    - targets: ['localhost:9100']
```

监控 CPU、内存、磁盘、网络。

---

## 七、数据库监控

### 7.1 PostgreSQL 监控

#### 慢查询

```sql
-- 启用慢查询日志
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- 1秒
ALTER SYSTEM SET log_statement = 'all';
SELECT pg_reload_conf();
```

#### pg_stat_statements

```sql
-- 安装扩展
CREATE EXTENSION pg_stat_statements;

-- 查看慢 SQL TOP 10
SELECT
  substring(query, 1, 100) as query,
  calls,
  total_exec_time,
  mean_exec_time,
  max_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

#### 连接数监控

```sql
-- 当前连接数
SELECT count(*) FROM pg_stat_activity;

-- 按状态分组
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;

-- 等待锁的连接
SELECT * FROM pg_stat_activity WHERE wait_event_type = 'Lock';
```

### 7.2 备份监控

```bash
# /etc/cron.daily/backup-hoimsystem
#!/bin/bash
DATE=$(date +%Y%m%d)
pg_dump -U postgres hoimsystem | gzip > /backups/hoimsystem-$DATE.sql.gz

# 验证备份
if [ ! -s /backups/hoimsystem-$DATE.sql.gz ]; then
  echo "Backup failed!" | mail -s "HIS-OP Backup FAILED" admin@example.com
fi

# 保留 30 天
find /backups -name "hoimsystem-*.sql.gz" -mtime +30 -delete
```

---

## 八、告警规则

### 8.1 业务告警

| 触发条件 | 告警级别 | 处置 |
|:--------|:--------:|:----|
| API 错误率 > 1%（5 分钟） | 🟡 警告 | 通知开发 |
| API 错误率 > 5%（5 分钟） | 🔴 严重 | 电话告警 |
| 登录失败次数 > 100/分钟 | 🔴 严重 | 可能被攻击 |
| 数据库连接数 > 90% | 🟡 警告 | 检查慢查询 |
| 磁盘使用率 > 85% | 🟡 警告 | 清理日志 |
| 磁盘使用率 > 95% | 🔴 严重 | 立即处理 |
| 后端进程崩溃 | 🔴 严重 | systemd 自动重启 |

### 8.2 Prometheus 告警规则示例

```yaml
# alert.yml
groups:
  - name: hoimsystem
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          / sum(rate(http_requests_total[5m])) > 0.05
        for: 5m
        annotations:
          summary: "API 错误率超过 5%"

      - alert: HighLatency
        expr: |
          histogram_quantile(0.95,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 1
        for: 5m
        annotations:
          summary: "P95 响应时间超过 1 秒"
```

---

## 九、运维 Runbook

### 9.1 故障应急流程

```
告警触发
  ↓
确认告警是否真实（避免误报）
  ↓
通知相关人员（@oncall）
  ↓
快速定位：
  - 看监控指标
  - 查日志
  - 看最近变更（最近合并的 PR）
  ↓
临时缓解：
  - 回滚？
  - 限流？
  - 重启？
  ↓
根因分析（事后复盘）
  ↓
长期修复（issue + PR）
  ↓
更新 Runbook
```

### 9.2 常见故障处置

#### 后端 500 错误增加

```bash
# 1. 看错误日志
tail -100 /var/log/hoimsystem/app.log | grep ERROR

# 2. 看 Sentry/告警平台
# 找出具体异常

# 3. 是不是最近发布引起的？
git log --since="1 hour ago" --oneline

# 4. 紧急回滚（参考 release-process.md）
```

#### 数据库连接耗尽

```bash
# 1. 看当前连接
psql -c "SELECT count(*) FROM pg_stat_activity;"

# 2. 找出长事务
psql -c "SELECT pid, query, age(now(), xact_start) FROM pg_stat_activity WHERE xact_start IS NOT NULL ORDER BY xact_start;"

# 3. 杀掉长事务（谨慎！）
psql -c "SELECT pg_terminate_backend(<pid>);"

# 4. 排查慢查询根因
```

#### 磁盘满

```bash
# 1. 找到大文件
du -sh /var/log/* | sort -rh | head -10

# 2. 清理日志
journalctl --vacuum-size=500M
find /var/log/hoimsystem -name "*.log.*" -mtime +7 -delete

# 3. 清理数据库膨胀
psql -c "VACUUM FULL hoimsystem_operation_log;"  # 谨慎，会锁表

# 4. 长期方案：
#    - 日志轮转
#    - 数据归档
#    - 扩容
```

---

## 十、当前监控现状

> ⚠️ 项目当前**未集成完整监控体系**，建议生产部署前补齐：

- [ ] 健康检查端点
- [ ] 应用日志规范化（结构化日志）
- [ ] Sentry 错误监控
- [ ] Prometheus 性能指标
- [ ] Grafana 监控看板
- [ ] 告警规则与通知渠道
- [ ] 备份与归档策略
- [ ] Runbook 文档

---

## 十一、参考资料

- [The Twelve-Factor App](https://12factor.net/zh_cn/)
- [Google SRE Book](https://sre.google/sre-book/table-of-contents/)
- [Prometheus 文档](https://prometheus.io/docs/)
- [Sentry FastAPI 集成](https://docs.sentry.io/platforms/python/integrations/fastapi/)
