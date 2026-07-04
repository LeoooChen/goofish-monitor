# AI Goofish Monitor

一个本地运行的闲鱼/Goofish 监控系统，包含 FastAPI 后端、React 前端、Playwright 浏览器登录与搜索、OpenAI 兼容 AI 分析。

## 功能

- 多账号管理：创建账号后用闲鱼扫码登录，登录态保存到 `data/accounts/*.json`。
- 页面二维码：登录时会保存闲鱼登录二维码截图，并在账号管理页面弹窗展示，适合 Docker 和云服务器扫码。
- 监控任务：标题、搜索关键词、描述、搜索页数、是否分析图片、自动启动频率。
- AI 设置：API 地址、API Key、模型名称、请求间隔。
- 微信提醒：AI 推荐度达到阈值时，通过企业微信群机器人发送商品链接和 AI 评价。
- 结果展示：商品瀑布流，按 AI 推荐、不推荐、未分析筛选，点击打开闲鱼链接。
- 账号保护：单任务串行、页面间随机等待、低频调度、出现验证/访问受限时自动停止。

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
uvicorn backend.app.main:app --reload
```

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

前端地址：`http://127.0.0.1:5173`

## Docker 启动

首次启动前先创建 `.env` 并设置访问密码：

```bash
cp .env.example .env
nano .env
```

至少修改：

```text
GOOFISH_ADMIN_PASSWORD=一段足够长的随机密码
GOOFISH_SESSION_SECRET=一段足够长的随机会话密钥
```

可以用下面的命令生成会话密钥：

```bash
openssl rand -base64 48
```

构建并启动：

```bash
docker compose up -d --build
```

如果服务器提示 `unknown command: compose`，说明 Docker 没有安装 Compose v2 插件。不要使用旧版 `docker-compose` v1；它在 Ubuntu Python 3.12 环境下可能因为缺少 `distutils` 崩溃。请安装 Compose v2 插件：

```bash
sudo apt update
sudo apt install docker-compose-plugin
docker compose version
docker compose up -d --build
```

访问地址：

```text
http://127.0.0.1:8000
```

查看日志：

```bash
docker compose logs -f
```

停止：

```bash
docker compose down
```

容器会把本地目录挂载到容器中：

- `./data:/app/data`
- `./logs:/app/logs`

如果在服务器或容器里扫码登录，打开 Web 页面后进入账号管理，点击账号的“登录”按钮，页面会弹出最新登录二维码或登录页截图。截图也会保存到 `data/login-qrcode/`，日志里仍会输出一次二维码预览。

## 服务器部署

仓库只提交源码、Docker 配置和前端 lockfile；本地数据、账号登录态、日志、Python 虚拟环境、前端依赖和构建产物都已忽略。服务器上 clone 后直接构建运行：

```bash
git clone https://github.com/<your-name>/goofish-monitor.git
cd goofish-monitor
cp .env.example .env
nano .env
docker compose up -d --build
```

如果 `docker compose` 不可用，先安装 Compose v2 插件：

```bash
sudo apt update
sudo apt install docker-compose-plugin
docker compose version
docker compose up -d --build
```

升级时：

```bash
git pull
docker compose up -d --build
```

首次构建会安装 Python 依赖、Node 依赖和 Playwright Chromium 浏览器，所以会比较慢。后续构建会复用 Docker 缓存：只改业务代码时不会重新下载这些依赖；只有修改 `requirements.txt`、`frontend/package-lock.json`、Dockerfile 相关依赖层，或者使用 `--no-cache`/清理 Docker 缓存后，才会重新安装。

Ubuntu 24.04/22.04 arm64 服务器如果 `apt` 找不到 `docker-compose-plugin`，需要先按 Docker 官方方式添加 Docker apt 源，安装包名仍然是 `docker-compose-plugin`。

## 访问密码

服务端会保护所有业务 API。未登录时只能访问登录页、健康检查和登录接口。登录成功后后端写入 `HttpOnly`、`SameSite=Lax` 的签名 Cookie。

默认使用 `.env` 里的 `GOOFISH_ADMIN_PASSWORD`。如果不想在服务器环境变量里保存明文密码，可以改用 scrypt 哈希：

```bash
docker compose run --rm ai-goofish-monitor python -c 'from backend.app.auth import hash_password; import getpass; print(hash_password(getpass.getpass("Password: ")))'
```

然后编辑 `.env`：

```text
GOOFISH_ADMIN_PASSWORD=
GOOFISH_ADMIN_PASSWORD_HASH=scrypt$...
```

`GOOFISH_SESSION_SECRET` 用于签名登录 Cookie。生产环境建议固定设置一段随机值，否则容器重启后已登录会话会失效。

## 反封控说明

本项目只做保守的频率控制和异常停止：串行执行任务、搜索页之间随机等待、可配置 AI 请求间隔、检测到安全验证时停止。没有实现验证码绕过、指纹伪装、代理池轮换或其他规避平台风控的能力。

## 数据文件

- `data/accounts.json`：账号列表。
- `data/accounts/*.json`：Playwright 登录态。
- `data/tasks.json`：监控任务。
- `data/settings.json`：系统设置。
- `data/results.json`：监控结果。
- `data/notifications.json`：已发送的微信提醒记录，用于避免重复提醒。
