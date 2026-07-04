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

构建并启动：

```bash
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
docker compose up -d --build
```

升级时：

```bash
git pull
docker compose up -d --build
```

## 反封控说明

本项目只做保守的频率控制和异常停止：串行执行任务、搜索页之间随机等待、可配置 AI 请求间隔、检测到安全验证时停止。没有实现验证码绕过、指纹伪装、代理池轮换或其他规避平台风控的能力。

## 数据文件

- `data/accounts.json`：账号列表。
- `data/accounts/*.json`：Playwright 登录态。
- `data/tasks.json`：监控任务。
- `data/settings.json`：系统设置。
- `data/results.json`：监控结果。
- `data/notifications.json`：已发送的微信提醒记录，用于避免重复提醒。
