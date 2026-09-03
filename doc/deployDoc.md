# 部署文档

## 一、环境要求

### 最低配置

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.10 | 后端运行环境 |
| Node.js | 20.19+ 或 22.12+ | 前端构建环境（Rspack 2 要求） |
| npm | >= 10.0.0 | 包管理器 |
| SQLite | 内置 | 开发环境默认数据库 |
| PostgreSQL | >= 14 | 生产环境推荐数据库 |

### 推荐生产配置

| 资源 | 配置 |
|------|------|
| CPU | 2 核及以上 |
| 内存 | 4 GB 及以上 |
| 磁盘 | 20 GB 及以上 |
| 带宽 | 5 Mbps 及以上 |

---

## 二、快速开始（开发环境）

### 2.1 克隆项目

```bash
git clone https://github.com/your-org/hoimsystem.git
cd hoimsystem
```

### 2.2 后端部署

```bash
cd fastapi_be

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端 API 将运行在 http://localhost:8000，自动文档地址：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 2.3 前端部署

```bash
cd vue3-new-ui

# 安装依赖
npm install --legacy-peer-deps

# 启动开发服务器
npm run serve:rspack
```

前端将运行在 http://localhost:8091。默认情况下前端通过 hash 路由直接访问后端 API（`http://localhost:8000/api`），请确保后端服务已启动。若需跨域代理，可在 `vue3-new-ui/config/proxy.js` 中配置。

---

## 三、生产环境部署

### 3.1 后端生产部署

#### 3.1.1 环境变量配置

复制环境变量模板并修改：

```bash
cd fastapi_be
cp .env.example .env
```

编辑 `.env` 文件：

```ini
# 生产环境标识：启用启动期安全校验
ENVIRONMENT=production

# 生产环境使用 PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/hoimsystem

# JWT 密钥（独立强随机值）
SECRET_KEY=replace-with-openssl-random-value

# 允许访问后端 API 的前端域名，多个域名用英文逗号分隔
ALLOWED_ORIGINS=https://his.example.com

# 生产环境禁止 ORM 自动建表，只允许 Alembic 迁移
AUTO_CREATE_SCHEMA=false

# 多实例实时事件和就绪探针
REDIS_URL=redis://localhost:6379/0

# API 进程不要运行定时任务；由独立 scheduler 服务运行
SCHEDULER_ENABLED=false

# 按实例数和 PostgreSQL max_connections 共同核算
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT_SECONDS=30
DB_POOL_RECYCLE_SECONDS=1800
DB_STATEMENT_TIMEOUT_MS=15000
```

**重要**：使用 `openssl rand -base64 48` 生成 `SECRET_KEY`；生产配置若仍使用自动建表、默认来源、通配符来源或非 HTTPS 出站地址，应用会拒绝启动。外部系统变量见 `.env.example` 与 [集成指南](integration-guide.md)。

#### 3.1.2 使用 Gunicorn 部署

```bash
cd fastapi_be
source .venv/bin/activate

# 安装 gunicorn
pip install gunicorn

# 先执行一次迁移，再启动 4 个 API worker；API worker 不运行调度器
python -m app.db_migrate
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 --access-logfile - --error-logfile -

# 在另一个受进程管理器监管的进程中启动调度器
SCHEDULER_ENABLED=true python -m app.scheduler_runner
```

#### 3.1.3 Systemd 服务配置

创建 `/etc/systemd/system/hoimsystem.service`：

```ini
[Unit]
Description=HIS-OP FastAPI Backend
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/hoimsystem/fastapi_be
Environment="PATH=/opt/hoimsystem/fastapi_be/.venv/bin"
EnvironmentFile=/opt/hoimsystem/fastapi_be/.env
ExecStart=/opt/hoimsystem/fastapi_be/.venv/bin/gunicorn app.main:app \
  -w 4 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

另建 `hoimsystem-scheduler.service`，使用相同的 `WorkingDirectory`、`EnvironmentFile` 和运行用户，将 `ExecStart` 设为：

```ini
ExecStart=/opt/hoimsystem/fastapi_be/.venv/bin/python -m app.scheduler_runner
```

调度器通过 PostgreSQL advisory lock 防止多实例重复执行，并把最近运行状态持久化到数据库。不要在多个 API worker 中同时设置 `SCHEDULER_ENABLED=true`。

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable hoimsystem
sudo systemctl start hoimsystem
sudo systemctl status hoimsystem
```

### 3.2 前端生产构建

```bash
cd vue3-new-ui

# 安装依赖
npm install --legacy-peer-deps

# 生产构建
npm run build
```

构建产物位于 `vue3-new-ui/dist/` 目录，为纯静态文件。

### 3.3 Nginx 配置

#### 3.3.1 前端静态文件 + API 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    location / {
        root /opt/hoimsystem/vue3-new-ui/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 反向代理
    location ^~ /api/ {
        # 不使用尾部斜杠，保留 /api 路径前缀
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 65s;
    }

    # SSE 临床事件流必须关闭代理缓冲；token 通过请求头传输，不写入 URL
    location /api/events/stream {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 75s;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

#### 3.3.2 HTTPS 配置（Let's Encrypt）

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 四、Docker 部署

项目已提供 Docker 支持，详见项目根目录 `docker-compose.yml`。

```bash
# Compose 会因缺失必填值而拒绝启动
export POSTGRES_PASSWORD='请替换为数据库强密码'
export SECRET_KEY="$(openssl rand -base64 48)"
export ALLOWED_ORIGINS='https://his.example.com'

# 启动 Redis、PostgreSQL、一次性迁移、API、独立调度器和前端
docker compose up -d

# 查看日志
docker compose logs -f migrate backend scheduler

# 停止
docker compose down
```

`migrate` 成功后 `backend`/`scheduler` 才会启动；`backend` 通过 `/health/ready` 探测数据库迁移和 Redis。PostgreSQL 与 Redis 只在 Compose 内网暴露，后端仅绑定宿主机 `127.0.0.1:8000`。升级时重新构建镜像并观察迁移容器退出码，禁止跳过迁移直接启动新代码。

---

## 五、数据库迁移

项目使用 Alembic 管理数据库迁移。

```bash
cd fastapi_be
source .venv/bin/activate

# 创建迁移脚本
alembic revision --autogenerate -m "add new table"

# 执行迁移（与生产 Compose 的 migrate 服务一致）
python -m app.db_migrate

# 回滚到上一个版本
alembic downgrade -1
```

---

## 六、常见问题

### Q1: 前端构建失败，提示 `ResizeObserver loop` 错误？

这是 Element Plus 组件的已知警告，不影响功能。已在 `main.js` 中配置拦截，生产构建时不会弹窗。

### Q2: 后端启动报错 `ModuleNotFoundError`？

确保在 `fastapi_be` 目录下运行，并激活虚拟环境：

```bash
cd fastapi_be
source .venv/bin/activate
export PYTHONPATH=$(pwd)
uvicorn app.main:app --reload
```

### Q3: 上传的图片/文件无法访问？

后端静态文件服务默认挂载在 `fastapi_be/app/uploads`；生产 Compose 已将宿主机同名目录挂载到容器 `/app/app/uploads`。确保目录存在且有写入权限：

```bash
mkdir -p fastapi_be/app/uploads
chmod 755 fastapi_be/app/uploads
```

### Q4: 如何修改默认端口？

前端：修改 `vue3-new-ui/rspack.config.js` 中的 `devServer.port`。
后端：启动命令添加 `--port YOUR_PORT`。

### Q5: 生产环境数据库从 SQLite 切换到 PostgreSQL？

1. 安装 PostgreSQL 并创建数据库
2. 修改 `fastapi_be/.env` 中的 `DATABASE_URL`
3. 运行 `alembic upgrade head` 创建表结构
4. （可选）使用脚本迁移历史数据

---

## 七、环境变量参考

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `ENVIRONMENT` | `development` | 运行环境。设为 `production` 时会强制检查生产安全配置 |
| `DATABASE_URL` | `sqlite:///./test.db` | 数据库连接字符串 |
| `SECRET_KEY` | 自动生成 | JWT 签名密钥，生产环境必须手动设置 |
| `ALLOWED_ORIGINS` | 本地开发地址 | CORS 允许来源白名单，多个来源用英文逗号分隔 |
| `AUTO_CREATE_SCHEMA` | `true` | 开发自动建表；生产必须为 `false` |
| `REDIS_URL` | 空 | Redis 地址；多实例事件广播与就绪检查使用 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `10` | 单进程连接池常驻/突发连接数 |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | 获取连接最大等待秒数 |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | 连接回收秒数 |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | PostgreSQL 单语句超时 |
| `SCHEDULER_ENABLED` | `true` | 是否运行定时任务；生产 API 应关闭、独立调度器开启 |
| `INTEGRATION_OUTBOX_INTERVAL_SECONDS` | `10` | 出站集成事件扫描间隔 |
| `INTEGRATION_HTTP_TIMEOUT_SECONDS` | `10` | 单次外部 HTTP 投递超时 |
| `INTEGRATION_MAX_ATTEMPTS` | `8` | 进入死信状态前的最大投递次数 |
| `DB_USER` | - | PostgreSQL 用户名（使用分项配置时） |
| `DB_PASSWORD` | - | PostgreSQL 密码（使用分项配置时） |
| `DB_HOST` | `localhost` | 数据库主机 |
| `DB_PORT` | `5432` | 数据库端口 |
| `DB_NAME` | `hoimsystem` | 数据库名 |
