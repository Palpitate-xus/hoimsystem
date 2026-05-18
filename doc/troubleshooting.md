# 常见问题与故障排查（FAQ）

> 本文档汇总开发、部署、运行过程中的常见问题与解决方案。
> 遇到问题先在这里搜索，没有再提 Issue。

---

## 一、环境与启动

### Q1: 后端启动报错 `ModuleNotFoundError: No module named 'app'`

**原因**：未在 `fastapi_be` 目录下运行，或 `PYTHONPATH` 未设置。

**解决**：
```bash
cd fastapi_be
source venv/bin/activate
export PYTHONPATH=$(pwd)
python -m uvicorn app.main:app --reload
```

---

### Q2: 后端启动报错 `Address already in use: 8000`

**原因**：8000 端口已被占用（可能旧后端未关闭）。

**解决**：
```bash
# 查看占用 8000 端口的进程
lsof -i :8000
# 或
netstat -tlnp | grep 8000

# 杀掉
kill -9 <PID>

# 或全部杀掉
pkill -9 -f 'uvicorn app.main'
```

---

### Q3: 前端启动报错 `node_modules` 相关错误

**原因**：依赖未安装或版本冲突。

**解决**：
```bash
cd vue3-new-ui
rm -rf node_modules package-lock.json
npm install --legacy-peer-deps
```

> ⚠️ `--legacy-peer-deps` 必须加，因为某些依赖有 peer dependency 冲突。

---

### Q4: 前端 `npm install` 速度慢

**原因**：默认从国外 npm registry 下载。

**解决**：
```bash
npm config set registry https://registry.npmmirror.com
npm install --legacy-peer-deps
```

---

### Q5: Python 依赖安装慢

**解决**：使用国内镜像源
```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 二、前端运行问题

### Q6: 浏览器访问前端是空白页

**可能原因 1**：`public/index.html` 中的 `<div id="...">` 与 `main.js` 中的 `app.mount("#...")` ID 不一致。

**检查**：
```bash
grep 'id=' vue3-new-ui/public/index.html
grep 'app.mount' vue3-new-ui/src/main.js
# 两者必须一致
```

**可能原因 2**：编译失败但 dev-server 没显示错误。

**解决**：查看终端日志，或刷新浏览器并打开 F12 控制台。

---

### Q7: 浏览器弹窗 `ResizeObserver loop completed with undelivered notifications`

**原因**：Element Plus 表格/resize 组件触发的浏览器无害警告，不影响功能。

**解决**：已在 `rspack.config.js` 中过滤：
```js
client: {
  overlay: {
    runtimeErrors: (error) => !error.message.includes("ResizeObserver"),
  },
}
```

修改后需要**重启** dev server（rspack 配置不支持热更新）。

---

### Q8: 前端编译错误 `ESModulesLinkingError: export 'xxx' was not found`

**原因**：前端代码导入了不存在的 API 函数。

**解决**：检查 `src/api/*.js` 中是否导出了该函数。常见情况：
- 函数名拼写错误（如 `getScheduleList` 应该是 `getDoctorScheduleList`）
- API 文件中漏定义

```bash
# 在前端代码中搜索导入
grep -rn 'import.*xxx' vue3-new-ui/src
```

---

### Q9: 前端登录后无法访问任何接口（一直 401）

**可能原因**：
- 后端未启动 → 检查 http://localhost:8000/
- token 未携带 → 检查浏览器 Network 面板，请求头是否含 `accesstoken`
- token 已过期 → 重新登录
- 后端 SECRET_KEY 改变 → 旧 token 失效，重新登录

---

### Q10: 前端跨域 CORS 错误

**原因**：dev-server 代理未生效，或生产环境 Nginx 未配置反向代理。

**开发环境**：检查 `rspack.config.js` 的 `proxy` 配置
```js
proxy: [{
  context: ["/api"],
  target: "http://localhost:8000",
  changeOrigin: true,
}]
```

**生产环境**：Nginx 配置 `/api/` 反向代理（见 [deployDoc.md](deployDoc.md)）

---

## 三、后端运行问题

### Q11: 接口报 500 错误 `relation/table ... does not exist`

**原因**：数据库表未创建。

**解决**：
```bash
# 删除 SQLite 文件让其重新创建
rm fastapi_be/test.db
# 重启后端，SQLAlchemy 自动建表
python -m uvicorn app.main:app --reload
```

PostgreSQL 环境使用 Alembic：
```bash
alembic upgrade head
```

---

### Q12: 操作日志一直为空

**原因**：在最近的更新前，操作日志写入功能未实现。

**解决**：确认 `app/main.py` 中是否注册了 `OperationLogMiddleware`：
```python
app.add_middleware(OperationLogMiddleware)
```

> 操作日志只记录 POST/PUT/DELETE 请求，GET 不记录。

---

### Q13: 上传文件 404

**原因**：上传目录不存在或权限问题。

**解决**：
```bash
mkdir -p fastapi_be/uploads
chmod 755 fastapi_be/uploads
```

后端启动时会自动创建：见 `app/main.py` 中的 `upload_dir`。

---

### Q14: 时间字段返回带微秒（如 `2026-05-18T14:30:45.123456`）

**原因**：`StripMicrosecondMiddleware` 未生效。

**解决**：确认 `app/main.py` 中：
```python
app.add_middleware(StripMicrosecondMiddleware)
```

> 注意：如果项目中创建了多个 FastAPI 实例（重复 `app = FastAPI(...)`），后定义的会覆盖前面的中间件配置。

---

### Q15: 登录失败 `账户或密码不正确`，但密码确认是对的

**可能原因**：
- 用户表中没有该用户
- 密码字段格式不对（应该是 bcrypt 哈希值）

**检查**：
```bash
sqlite3 fastapi_be/test.db "SELECT username, password FROM hoimsystem_users WHERE username='admin';"
# 正常的 password 应该是以 $2b$ 开头的 60 字符 bcrypt 哈希
```

**重置 admin 密码**：
```python
# 在 fastapi_be/ 下运行
python -c "
import bcrypt
from app.database import SessionLocal
from app.models import User

pwd = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
db = SessionLocal()
admin = db.query(User).filter(User.username == 'admin').first()
if admin:
    admin.password = pwd
    db.commit()
    print('Reset admin password to admin123')
else:
    print('admin user not found')
"
```

---

## 四、数据库问题

### Q16: SQLite 文件位置在哪？

默认在 `fastapi_be/test.db`（相对路径，由 `.env` 中的 `DATABASE_URL=sqlite:///./test.db` 决定）。

> 注意：实际位置取决于启动后端时的**当前工作目录**。如果在 `fastapi_be` 目录启动，文件在 `fastapi_be/test.db`。

---

### Q17: 如何重置数据库到空白？

**SQLite**：
```bash
rm fastapi_be/test.db
# 重启后端自动建表
```

**PostgreSQL**：
```bash
dropdb hoimsystem
createdb hoimsystem
alembic upgrade head
```

---

### Q18: 如何从 SQLite 迁移到 PostgreSQL？

```bash
# 1. 导出 SQLite 数据
sqlite3 fastapi_be/test.db .dump > backup.sql

# 2. 简单方案：手动调整 SQL 兼容 PostgreSQL（数据类型、AUTOINCREMENT 等）

# 3. 推荐方案：用 pgloader
pgloader sqlite://fastapi_be/test.db postgresql://localhost/hoimsystem

# 4. 修改 .env
echo "DATABASE_URL=postgresql://localhost/hoimsystem" > fastapi_be/.env
```

---

### Q19: 数据库查询慢

**排查步骤**：
```python
# 临时打开 SQL 日志
from app.database import engine
import logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

**常见原因**：
- 缺少索引（外键、where 常用字段）
- N+1 查询（用 `joinedload` 预加载关联）
- 大表全扫描（加分页）

---

## 五、Git/部署问题

### Q20: 推送时报错 `Updates were rejected`

**原因**：本地分支落后于远程。

**解决**：
```bash
# 安全方式：拉取后再推送
git pull --rebase origin master
git push

# 强制推送（仅个人分支，主分支严禁）
git push --force-with-lease
```

---

### Q21: 部署后 502 Bad Gateway

**原因**：Nginx 无法连接到后端。

**排查**：
```bash
# 1. 后端是否运行？
systemctl status hoimsystem
curl http://127.0.0.1:8000/

# 2. Nginx 配置是否正确？
nginx -t
cat /etc/nginx/sites-enabled/hoimsystem

# 3. 防火墙？
ufw status
```

---

### Q22: Docker 容器无法访问宿主机数据库

**原因**：容器内 `localhost` 指容器自己，不是宿主机。

**解决**：使用 `host.docker.internal`（Mac/Win）或宿主机的实际 IP（Linux）：
```yaml
# docker-compose.yml
environment:
  DATABASE_URL: postgresql://user:pass@host.docker.internal:5432/hoimsystem
```

或将数据库也容器化：
```yaml
services:
  postgres:
    image: postgres:15
    ...
  backend:
    depends_on: [postgres]
    environment:
      DATABASE_URL: postgresql://user:pass@postgres:5432/hoimsystem
```

---

## 六、性能问题

### Q23: 列表页加载慢

**前端排查**：
- 检查浏览器 Network 面板，看 API 响应时间
- 检查是否一次性渲染了 1000+ 行（应该用分页）

**后端排查**：
- 加日志看是哪个查询慢
- 检查是否有 N+1 查询
- 添加索引

---

### Q24: 首屏加载慢

**原因**：JS bundle 过大。

**解决**：
- 路由懒加载（已开启）
- 拆 vendor chunk
- 启用 gzip 压缩（Nginx 配置）

```nginx
gzip on;
gzip_types text/plain application/javascript application/json text/css;
gzip_min_length 1024;
```

---

## 七、安全相关

### Q25: 如何禁用默认账号？

```bash
# 删除默认账号
sqlite3 fastapi_be/test.db "DELETE FROM hoimsystem_users WHERE username IN ('admin', 'doctor1', 'patient1');"

# 或修改密码
python -c "..."  # 参考 Q15
```

---

### Q26: 生产环境 SECRET_KEY 怎么设置？

```bash
# 生成一个强随机密钥
openssl rand -base64 32

# 写入 .env
echo "SECRET_KEY=$(openssl rand -base64 32)" >> .env
```

> ⚠️ 修改 SECRET_KEY 后所有已签发的 token 都会失效，用户需要重新登录。

---

### Q27: 如何启用 HTTPS？

使用 Let's Encrypt 免费证书：
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

证书会自动配置到 Nginx，并设置自动续期。

---

## 八、调试技巧

### 8.1 后端日志

```bash
# 实时查看日志
tail -f /tmp/backend.log

# 启动时打开详细日志
python -m uvicorn app.main:app --reload --log-level debug
```

### 8.2 前端日志

```bash
# 实时查看 dev-server 日志
tail -f /tmp/frontend.log

# 浏览器 F12 控制台
# - Console: JS 错误、console.log
# - Network: API 请求/响应
# - Application: localStorage、Cookie
```

### 8.3 数据库查询

```bash
# 进入 SQLite shell
sqlite3 fastapi_be/test.db
sqlite> .tables                              # 列出所有表
sqlite> .schema hoimsystem_user              # 查看表结构
sqlite> SELECT * FROM hoimsystem_user LIMIT 10;
sqlite> .quit
```

### 8.4 用 curl 测试 API

```bash
# 登录获取 token
TOKEN=$(curl -s -X POST http://localhost:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['accesstoken'])")

# 调用需要鉴权的接口
curl -s http://localhost:8000/api/patientManagement/getList \
  -H "accesstoken: $TOKEN" | python3 -m json.tool
```

---

## 九、问题模板

提 Issue 时请提供：

```markdown
**环境**：
- OS：macOS 14.0 / Ubuntu 22.04 / Windows 11
- Python：3.10.x
- Node：20.x
- 浏览器：Chrome 120

**操作步骤**：
1. ...
2. ...
3. ...

**预期行为**：
...

**实际行为**：
...

**错误日志**：
```
[粘贴完整错误信息]
```

**截图**（如有）
```

---

## 十、求助渠道

1. **本文档**：先搜关键词
2. **GitHub Issues**：搜索类似问题
3. **架构文档**：[architecture.md](architecture.md)
4. **新提 Issue**：使用上面的模板
5. **团队群**：紧急问题可在群里 @ 相关开发
