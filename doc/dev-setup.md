# 开发环境搭建指南

> 本文档面向**新加入项目的开发者**，提供从零搭建本地开发环境的完整步骤。
> 如果只想快速运行项目，请参考主 [README 快速开始](../README.md#-快速开始)。

---

## 一、前置工具安装

### 1.1 必装软件

| 工具 | 版本要求 | 用途 | 安装方式 |
|:----:|:--------:|:----|:--------|
| **Git** | ≥ 2.30 | 版本控制 | [官网](https://git-scm.com/) / `apt install git` / `brew install git` |
| **Python** | ≥ 3.10 | 后端运行环境 | [官网](https://www.python.org/) / pyenv / conda |
| **Node.js** | ≥ 16 | 前端构建环境 | [官网](https://nodejs.org/) / nvm |
| **VS Code** | latest | 推荐 IDE | [官网](https://code.visualstudio.com/) |

### 1.2 推荐工具

| 工具 | 用途 |
|:----:|:----|
| **pyenv / conda** | Python 多版本管理 |
| **nvm** | Node.js 多版本管理 |
| **Docker Desktop** | 容器化开发 |
| **DBeaver / Navicat** | 数据库可视化工具 |
| **Postman / Apifox** | API 测试 |
| **Sourcetree / GitKraken** | Git GUI |

### 1.3 Linux/WSL 环境

如果使用 Linux/WSL，建议先安装基础包：

```bash
sudo apt update
sudo apt install -y git curl wget build-essential python3 python3-pip python3-venv nodejs npm
```

---

## 二、克隆与初始化

### 2.1 克隆仓库

```bash
git clone https://github.com/Palpitate-xus/hoimsystem.git
cd hoimsystem

# 配置 Git 用户信息（如未配置）
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### 2.2 项目结构概览

```
hoimsystem/
├── fastapi_be/       # 后端 (Python + FastAPI)
├── vue3-new-ui/      # 前端 (Vue 3 + Element Plus)
├── doc/              # 项目文档
├── doc_assets/       # 文档资源
└── docker-compose.yml
```

---

## 三、后端开发环境

### 3.1 Python 虚拟环境

强烈推荐使用虚拟环境避免依赖冲突：

```bash
cd fastapi_be

# 方式一：venv（Python 自带）
python -m venv venv
source venv/bin/activate              # Linux/Mac
# venv\Scripts\activate.bat           # Windows CMD
# .\venv\Scripts\Activate.ps1         # Windows PowerShell

# 方式二：conda
conda create -n hoim python=3.10
conda activate hoim
```

### 3.2 安装依赖

```bash
pip install -r requirements.txt

# 国内用户可用清华镜像加速
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 3.3 环境变量配置

```bash
# 复制环境变量模板
cp .env.example .env  # 如果有模板的话

# 或手动创建 .env
cat > .env <<EOF
DATABASE_URL=sqlite:///./test.db
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
EOF
```

> ⚠️ `.env` 文件已在 `.gitignore` 中，不会被提交。每个开发者本地维护自己的副本。

### 3.4 启动后端

```bash
# 开发模式（自动重载）
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 后台运行
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
```

启动成功后访问：
- API 根：http://localhost:8000/
- Swagger UI：http://localhost:8000/docs
- ReDoc：http://localhost:8000/redoc

### 3.5 数据库初始化

**SQLite（推荐开发环境）**：首次启动后端时 SQLAlchemy 会自动创建所有表。

**PostgreSQL（高级开发场景）**：
```bash
# 1. 创建数据库
createdb hoimsystem_dev

# 2. 修改 .env
echo "DATABASE_URL=postgresql://localhost:5432/hoimsystem_dev" > .env

# 3. 启动后端，自动建表
python -m uvicorn app.main:app --reload
```

---

## 四、前端开发环境

### 4.1 安装依赖

```bash
cd vue3-new-ui

# 安装（注意 --legacy-peer-deps 处理 peer dependency 冲突）
npm install --legacy-peer-deps

# 国内用户可用淘宝镜像加速
npm config set registry https://registry.npmmirror.com
npm install --legacy-peer-deps
```

### 4.2 启动前端

```bash
# 开发模式（端口 8091，自动打开浏览器）
npm run serve:rspack
```

启动成功后访问：http://localhost:8091

### 4.3 前端代理配置

前端 dev server 已配置 `/api/*` 代理到 `http://localhost:8000`，无需额外配置。
代理配置位置：[vue3-new-ui/rspack.config.js](../vue3-new-ui/rspack.config.js)

---

## 五、IDE 配置

### 5.1 VS Code 推荐扩展

**通用：**
- GitLens
- GitHub Pull Requests
- Markdown All in One
- Code Spell Checker

**Python：**
- Python (Microsoft)
- Pylance
- Ruff（代码检查）
- Black Formatter（可选）

**Vue/JavaScript：**
- Vue - Official (`Vue.volar`)
- ESLint
- Prettier
- Auto Rename Tag
- Path Intellisense

### 5.2 VS Code 工作区配置

在项目根创建 `.vscode/settings.json`：

```json
{
  "python.defaultInterpreterPath": "fastapi_be/venv/bin/python",
  "python.analysis.extraPaths": ["fastapi_be"],
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff"
  },
  "[vue]": {
    "editor.defaultFormatter": "Vue.volar"
  },
  "[javascript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": "explicit",
    "source.organizeImports": "explicit"
  }
}
```

### 5.3 调试配置

`.vscode/launch.json`：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI Backend",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": ["app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
      "cwd": "${workspaceFolder}/fastapi_be",
      "jinja": true
    },
    {
      "name": "Pytest Current File",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v"],
      "cwd": "${workspaceFolder}/fastapi_be"
    }
  ]
}
```

---

## 六、测试账号

后端首次启动时自动创建以下账号（如不存在则插入）：

| 角色 | 用户名 | 密码 |
|:----:|:------:|:----:|
| 管理员 | admin | admin123 |
| 医生 | doctor1 | doctor123 |
| 患者 | patient1 | patient123 |

更多默认账号见 [user-manual.md](user-manual.md)。

---

## 七、常用开发命令速查

### 后端

```bash
# 启动开发服务器
python -m uvicorn app.main:app --reload

# 运行测试
pytest tests/ -v

# 代码格式化
ruff check . --fix
ruff format .

# 数据库迁移（Alembic）
alembic revision --autogenerate -m "描述"
alembic upgrade head
alembic downgrade -1

# 重置数据库（开发环境，谨慎！）
rm test.db && python -m uvicorn app.main:app --reload
```

### 前端

```bash
# 开发服务器
npm run serve:rspack

# 生产构建
npm run build

# 清理 node_modules 重装
rm -rf node_modules package-lock.json
npm install --legacy-peer-deps
```

### Git

```bash
# 查看分支
git branch -a

# 创建并切换到新分支
git checkout -b feature/your-feature

# 同步主分支
git fetch origin
git rebase origin/master

# 推送
git push origin feature/your-feature
```

---

## 八、新人 Onboarding Checklist

- [ ] 安装 Git、Python 3.10+、Node 16+、VS Code
- [ ] Clone 仓库到本地
- [ ] 阅读 [README.md](../README.md) 和 [architecture.md](architecture.md)
- [ ] 启动后端，访问 `http://localhost:8000/docs` 查看 API
- [ ] 启动前端，访问 `http://localhost:8091` 登录系统
- [ ] 使用 admin/admin123 登录，浏览各模块
- [ ] 跑通至少一个完整业务流程（如：患者预约→医生开方→药师发药）
- [ ] 阅读 [coding-standards.md](coding-standards.md) 了解代码规范
- [ ] 阅读 [git-workflow.md](git-workflow.md) 了解提交规范
- [ ] 尝试改一行代码并提交一个 PR

---

## 九、遇到问题？

1. 先查 [troubleshooting.md](troubleshooting.md) 常见问题
2. 看 [部署文档](deployDoc.md) 的环境配置部分
3. 在 GitHub Issues 搜索类似问题
4. 提新 Issue 或在团队群提问
