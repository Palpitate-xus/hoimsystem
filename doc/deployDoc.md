# 部署文档

## 一、环境要求

### 最低配置

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.10 | 后端运行环境 |
| Node.js | >= 16.0.0 | 前端构建环境 |
| npm | >= 7.0.0 | 包管理器 |
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
# 生产环境标识：启用后后端会拒绝默认/空 SECRET_KEY
ENVIRONMENT=production

# 生产环境使用 PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/hoimsystem

# JWT 密钥（必须修改为随机强密钥！）
SECRET_KEY=your-random-secret-key-min-32-chars

# 允许访问后端 API 的前端域名，多个域名用英文逗号分隔
ALLOWED_ORIGINS=https://his.example.com
```

**重要**：`SECRET_KEY` 必须使用 `openssl rand -base64 32` 或类似命令生成随机密钥，切勿使用默认值。

#### 3.1.2 使用 Gunicorn 部署

```bash
cd fastapi_be
source .venv/bin/activate

# 安装 gunicorn
pip install gunicorn

# 启动（4 个工作进程）
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 --access-logfile - --error-logfile -
```

#### 3.1.3 Systemd 服务配置

创建 `/etc/systemd/system/hoimsystem.service`：

```ini
[Unit]
Description=HIS-OP FastAPI Backend
After=network.target

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
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
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
# 一键启动全部服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

---

## 五、数据库迁移

项目使用 Alembic 管理数据库迁移。

```bash
cd fastapi_be
source .venv/bin/activate

# 创建迁移脚本
alembic revision --autogenerate -m "add new table"

# 执行迁移
alembic upgrade head

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

后端静态文件服务默认挂载在 `fastapi_be/app/uploads`，确保该目录存在且有写入权限：

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
| `DB_USER` | - | PostgreSQL 用户名（使用分项配置时） |
| `DB_PASSWORD` | - | PostgreSQL 密码（使用分项配置时） |
| `DB_HOST` | `localhost` | 数据库主机 |
| `DB_PORT` | `5432` | 数据库端口 |
| `DB_NAME` | `hoimsystem` | 数据库名 |
