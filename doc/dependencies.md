# 依赖与镜像维护

应用使用 Python 3.12 与 Node.js 24 构建。Python、npm 和系统软件包分别审计；npm/PyPI 无已知告警不等于整个容器没有漏洞。

## 可复现安装

`fastapi_be/requirements*.txt` 是依赖输入，18 份对应的 `.lock` 固定完整传递依赖和 SHA-256。`dependencies-lock-manifest.json` 同时校验输入和锁文件，修改输入后必须重新解析并审计。

```bash
cd fastapi_be
python -m pip install --require-hashes -r requirements-build.lock
python -m pip install --only-binary=:all: --require-hashes -r requirements.lock
python scripts/lock_dependencies.py
```

锁文件针对 Python 3.12、Linux x86_64 解析。数值测试另装 `requirements-test.lock`；ECG、影像、语音与规则服务各自使用对应锁文件，模型运行库不会进入普通 API 环境。

```bash
python scripts/lock_dependencies.py --update
python scripts/audit_dependencies.py --output /tmp/hoim-dependency-audit-001
```

解析仅使用官方 PyPI，以及模型输入指定的官方 PyTorch CPU 索引。模型数值库保持已审核的组合：Torch 2.14.1+cpu、NumPy 2.4.4、Safetensors 0.8.0；语音使用 Faster Whisper 1.2.1、PyAV 16.1.0 等兼容组合。升级这些组件需要重新核对引擎身份、协议与数值行为。

审计器检查全部锁文件，保留失败和跳过原因。官方 CPU wheel 的 `+cpu` 属于本地版本标记，安全公告查询使用对应的 PyTorch 公共版本；安装版本和哈希保持原样。审计目录必须是新目录，避免覆盖旧证据。

前端使用 `npm ci --legacy-peer-deps`；升级后运行 `npm run test:unit`、`npm run audit`、`npm run build` 和 `npm run check:bundle`。全局 Sass 使用 `@use`，Element Plus 样式与公开文本池由正式生成器核对，不删除来源数据来压缩构建产物。

## 镜像与媒体组件

Dockerfile 固定官方基础镜像摘要。NGINX 1.30.6 Alpine 在构建时应用发行版安全更新。PostgreSQL 保持既有主版本，Redis 保持 8.x；数据库主版本不能随依赖更新自动切换。

API 与语音镜像从 FFmpeg 官方签名源码构建 9.0.2，源码地址、SHA-256 与签名指纹保存在 `fastapi_be/ffmpeg-source.json`。运行镜像只保留音频读取和 PCM 输出所需的工具，关闭网络协议；编译工具和无关的外部图像、设备库不进入运行镜像。

`fastapi_be/scripts/smoke_audio_runtime.py` 使用六种合成音频检查实际解码、时长和协议列表。测试仅验证媒体处理工程链路。

```bash
docker run --rm --network none \
  --mount type=bind,src="$PWD/fastapi_be/tests/fixtures/audio",dst=/fixtures,readonly \
  -e SECRET_KEY=local-audio-runtime-check-at-least-32-characters \
  hoimsystem-preview-backend:local \
  python scripts/smoke_audio_runtime.py --fixtures /fixtures
```

容器层使用 Grype 单独扫描，并保存原始结果；不隐藏发行版未修复项，也不把跨 Python 分支的 CPE 匹配直接当作已修复。本轮更新与残留项见 [依赖、体验与持续负载验证](validation/2026-10-28-optimization.md)。

## 更新与发布

Dependabot 每周检查 pip、npm 与 Docker，相关更新按组提交，每类最多保留一个版本更新 PR。依赖更新不自动合并，锁文件、测试和镜像审计通过后再发布。仓库沿用本地验证流程，不新增 GitHub Actions。

发布前运行 `python scripts/check_release.py`，同时核对版本号、依赖哈希、RBAC、80 项能力与 Prompt、前端生成数据、体积预算和 Compose。发布步骤见 [发布流程](release-process.md)。
