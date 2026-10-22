# Deckpit — 自建 Linux 开发者工作台

> **Deckpit** = Deck（甲板/卡片面板）+ Cockpit（驾驶舱）——一块卡片式面板，当你的开发驾驶舱。

一个运行在 `http://localhost:8787` 的本地 Web 工作台，把开发者日常高频操作——**命令速查、文件管理、端口/进程、终端、系统监控、日志、环境、SSH、Docker**——统一到一个页面里：可看、可搜、可点、可拖。

面向单用户（开发者本人），基准环境 **Ubuntu 22.04 + GNOME**，零外网依赖。默认监听 `0.0.0.0:8787` 以便局域网内其他机器访问，但**本机访问免登录、非本机访问需账号密码**（未配置口令时非本机一律拒绝）。

## 解决什么问题

多项目并行开发时，桌面被一堆终端窗口和文件管理器塞满："这个端口被谁占了？"、"哪个终端跑的是哪个服务？"、"那条命令上次怎么写的来着？"——本项目把答案收进一个浏览器标签页：

| 痛点 | 对应模块 |
|------|----------|
| 常用指令记不住、反复上网查 | 命令手册 + 悬浮小屏 |
| 文件夹开多了找不到、新建文件靠命令行 | 文件管理器 |
| 端口占用不知道是哪个服务、哪启动的 | 端口监控 |
| 多终端不知道哪个跑啥 | 终端中心（可命名/状态灯） |
| 命令历史搜索弱、alias 散乱 | 终端历史 + shell 历史自动同步 |
| 多服务日志分散、GPU/CPU 监控 | 日志查看器 + 系统监控 |
| 多 venv / Node 版本 / .env 串味 | 环境管理 |
| SSH 会话散乱 | SSH 管理 + 一键连接 |

## 功能总览

### 🖥️ 首页面板
- CPU / 内存 / GPU / 磁盘实时状态条（点击跳转系统监控）
- 各模块快捷入口卡片（带运行状态摘要）
- **常用终端**：备注 + 路径，一键在本机打开外部终端
- **服务运行管理**：把一个项目服务定义为「多步骤启动命令 + 占用端口 + 工作目录」，支持启动 / 停止 / 状态查看 / 端口监听检查 / 开机自启
- 磁盘大文件 Top、项目（Project）聚合管理

### 📖 命令手册
- 出厂预置 50+ 常用 Linux 命令（文件 / 网络 / 进程 / 磁盘 / AI / Docker / Git 等分类）
- 每条含用途说明、参数逐项解释、使用示例
- 中英文模糊搜索、收藏置顶、自定义增删改、一键复制
- **四来源命令历史自动收录**：面板终端输入、外部终端发送、手册发送、`~/.bash_history` / `~/.zsh_history` 后台增量同步；历史可一键转存为命令条目
- JSON 导入 / 导出，使用频次统计与 Top 榜

### 📁 文件管理器
- 目录浏览 + 面包屑导航 + 路径直接跳转
- 新建文件/文件夹、重命名、删除、复制、移动（删除需二次确认）
- 快捷位置书签、最近打开文件、文件模板库（.py / .sh / Dockerfile / .env / docker-compose.yml 等 8 种）
- 右键联动：在此打开终端 / 用 VSCode 打开 / 复制绝对路径 / 系统文件管理器打开
- 磁盘占用方块图（du 下钻）、检测并管理桌面已开的 Nautilus 窗口（聚焦 / 关闭 / 别名）

### 🔌 端口监控
- 监听端口表格：端口号 / 协议 / 状态 / PID / 进程名 / 启动命令 / 启动路径
- 行展开详情：完整 cmdline、工作目录、启动用户、**父进程链**（一眼看清服务由谁拉起）
- 一键 kill（SIGTERM / SIGKILL，二次确认）、自动刷新
- 全量进程列表（按 CPU / 内存排序、搜索）、systemd user/system 服务管理（start/stop/restart/enable）
- 僵尸 / 孤儿进程识别、端口快照保存与差异对比

### ⌨️ 终端中心（核心）
- **内嵌 xterm.js 多标签 PTY 终端**：每标签独立会话，双击命名（如 "AI-推理服务"、"前端-nginx"）
- 状态灯（绿=空闲 / 黄=有输出）、resize、选择 shell 与初始目录
- **会话持久化**：PTY 进程活在后端，刷新 / 重开页面后自动恢复（scrollback 回放 + 接实时流）
- **外部终端窗口控制**（wmctrl + xdotool）：列出本机所有终端窗口、设别名、聚焦 / 关闭 / 直接向指定窗口发送命令执行
- 命令发送到当前活动终端、tmux 会话列表与接管

### 📊 系统监控
- CPU（总体 + 每核）、内存 + Swap、磁盘 I/O 与分区、网络速率实时曲线（ECharts，2s 刷新，保留 5 分钟历史）
- **GPU 监控**（pynvml）：每卡显存 / 利用率 / 温度 / 功耗 / 风扇；无 N 卡时自动隐藏
- GPU 进程列表与详情（进程名 / 命令行 / 工作目录 / 父进程链）
- 磁盘大文件 Top（识别模型权重）、系统依赖（wmctrl/xdotool）检查与一键安装

### 📄 日志查看器
- 大文件分页流式读取（>100MB 不卡）+ 实时 tail 模式（WS 推送，可暂停）
- 级别自动高亮（ERROR 红 / WARN 黄 / INFO 蓝）、正则搜索、关键词过滤、多日志标签页
- 多日志聚合视图、时间戳时间线对齐、ERROR 出现触发告警订阅

### 🐍 环境管理
- 自动探测 Python（系统 / venv / Conda）/ Node（nvm）/ uv / CUDA 环境，支持自定义路径扫描与备注
- 每环境包列表（优先 uv，回退 pip/conda）、一键导出 requirements.txt、两环境包差异对比
- `.env` 查看与编辑（敏感值默认打码，可切换原文）
- CUDA / Driver / PyTorch / TensorFlow 版本与兼容性提示

### 🔗 SSH 管理
- 主机 CRUD（名称 / IP / 端口 / 用户 / 密钥 / 跳板机）+ 在线状态探测（ping + TCP）
- 一键连接：自动在终端中心新开标签执行 ssh
- 远程路径收藏、`~/.ssh/config` 解析与一键导入

### 🐳 Docker 管理
- 容器列表 / 详情 / 日志 / 资源统计，容器操作（start / stop / restart / kill / rm）
- 镜像列表与拉取、Compose 项目（up / down / restart / ps / config）
- 卷、网络管理、系统信息与一键 prune

### 🎯 悬浮小屏（QuickPalette）
- pywebview 无边框置顶小窗，聚合「命令手册 + 终端历史」模糊查找
- **AI 模式**：在悬浮窗里直接提问，复用网页端会话、流式输出、token 统计和动作确认；模型配置只在网页端「AI 助手 → 设置」提供
- AI 模式默认使用更紧凑的字号；底部「尺寸」可设置默认窗口大小，切换到 AI 时自动应用，切回命令模式恢复原尺寸
- **自动吸附**：检测到你在用终端时贴其右缘显示，切走自动隐藏
- 全局快捷键 `Ctrl+Shift+Space` 唤起，系统托盘常驻；支持"点即发送到活动终端"

### 🤖 AI 助手
- 右侧抽屉，`Alt+A` 唤起；支持多轮、流式输出、Markdown/代码块、会话历史
- 每次回复结束展示本会话累计 token（输入 / 输出 / 合计）；模型未返回 usage 时自动标记“估算”
- 每个代码块和整条回复都有复制按钮；局域网 HTTP 访问时会回退到兼容复制方式
- **配置百科**：直接问「我配置了哪些服务」「MyDashboard 后端怎么启动、端口多少」「我有哪些常用终端」「哪些容器在运行」，AI 会读项目/服务/命令/终端/SSH/Docker/日志源/环境配置，并区分“配置值”和“当前状态”
- **白名单启停**：对已有服务、Docker 容器/Compose 提议 start / stop / restart；必须点确认才执行，执行后展示“前 → 后”状态
- 模型走 OpenAI-compatible 协议，本地 Ollama / vLLM 优先，也可接 DeepSeek / OpenAI；API Key 服务端加密存储
- 明确不做：任意命令执行、文件读写、进程 kill、Docker 删除/prune、SSH 远端执行、向终端注入命令

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 + FastAPI + Uvicorn + aiosqlite |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router |
| 终端 | xterm.js + Python `pty`（fork + PTY 池管理） |
| 图表 | ECharts (vue-echarts) |
| 实时通信 | WebSocket（终端 I/O / 监控推送 / 日志 tail 三通道） |
| AI | OpenAI-compatible（Ollama / vLLM / DeepSeek / OpenAI）+ `httpx` 流式 |
| Markdown | markdown-it + highlight.js + DOMPurify |
| 系统采集 | psutil + pynvml + `ss` / `/proc` 解析 |
| 桌面集成 | wmctrl + xdotool + pywebview（悬浮小屏） |
| 存储 | SQLite 单文件（19 张表） |
| 部署 | venv + systemd user service |

## 架构

```
┌──────────────────────────────────────────────────────┐
│  浏览器 http://localhost:8787                         │
│  Vue3 SPA ── Element Plus ── xterm.js ── ECharts     │
└──────┬────────────────────────┬──────────────────────┘
       │ REST (/api/*)          │ WebSocket (/ws/*)
       ▼                        ▼
┌──────────────────────────────────────────────────────┐
│  FastAPI (uvicorn, :8787)                            │
│  ├─ routers/   10 个模块路由（命令/文件/端口/终端/     │
│  │             监控/日志/环境/SSH/首页/Docker）        │
│  ├─ services/  PTY 池·端口解析·监控采样·Docker CLI·    │
│  │             外部终端控制·shell 历史同步·tmux 等     │
│  ├─ ws/        终端桥接 / 监控推送 / 日志 tail         │
│  └─ SQLite     data/dashboard.db（14 张表）           │
└──────┬───────────┬──────────────┬────────────────────┘
       ▼           ▼              ▼
   psutil/      pty +         subprocess
   pynvml       bash/zsh      (ss, docker, wmctrl,
   /proc                       xdotool, systemctl...)
```

三类数据流：CRUD 走 REST；监控指标 / 日志增量走服务端 WS 推送；终端 stdin/stdout 走双向 WS。

## 部署

### 先理解它的权限等级

Deckpit 以**运行它的那个用户**的身份工作，能力边界 = 该用户的 shell：

| 能力 | 范围 |
|------|------|
| 执行命令 | 任意命令（内嵌 PTY 终端、向外部终端注入、服务启动脚本） |
| 文件读写 | 该用户有权访问的全部路径（默认 `ALLOWED_ROOTS = /`） |
| 进程管理 | 结束该用户的任意进程、管理 systemd 用户服务 |
| Docker | 若用户在 `docker` 组，等同 root（可挂载宿主机目录） |
| 敏感信息 | 读取项目 `.env`、SSH 配置 |

三条红线：**不要用 root 运行**、**不要把端口暴露到公网**、**口令不要用弱密码**。

### 一键部署（新机器推荐）

```bash
./scripts/setup.sh
```

向导依次处理（每一步都会先显示将要执行的命令再确认）：

| 步骤 | 内容 |
|------|------|
| 1 权限确认 | root 运行时告警并建议中止；docker 组用户额外提示 |
| 2 依赖预检 | 调用 `check-env.sh`，输出 PASS/WARN/FAIL |
| 3 系统依赖 | `sudo apt install` 补齐 `ss/curl/tmux/wmctrl/xdotool/xprop` |
| 4 运行环境 | 建 `backend/.venv`、装 pip 依赖、构建 `frontend/dist` |
| 5 监听范围 | 选 `0.0.0.0`（局域网，非本机来源需登录）或 `127.0.0.1`（仅本机） |
| 6 登录口令 | 生成 20 位随机口令写入 `~/.config/deckpit.env`（权限 600） |
| 7 防火墙 | `sudo ufw allow from <内网段> to any port 8787`，只放行内网 |
| 8 开机自启 | 安装 systemd 用户服务并 enable，输出日志命令 |

非交互（全部采用推荐默认值）：`DASH_SETUP_YES=1 ./scripts/setup.sh`

部署后随时自检：`./scripts/check-env.sh`（含口令/权限/防火墙等安全项核对）。

### 依赖清单（手动部署时对照）

| 依赖 | 用途 | 缺失后果 | 安装 |
|------|------|----------|------|
| uv | 管理 Python 环境 | 无法创建 venv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python ≥ 3.10 | 后端运行时 | 无法启动 | 随 uv 安装 |
| Node ≥ 18 | 构建前端 dist | dist 缺失则生产模式无法运行 | `nvm install 20` |
| `ss`（iproute2） | 端口监控 | 端口模块不可用 | `sudo apt install -y iproute2` |
| `curl` | 健康检查 / 依赖安装 | 部分检查跳过 | `sudo apt install -y curl` |
| **tmux** | **远程接管外部终端** | 接管按钮禁用 | `sudo apt install -y tmux` |
| `wmctrl`/`xdotool`/`xprop` | 外部终端窗口控制 | 外部终端列表为空 | `sudo apt install -y wmctrl xdotool x11-utils` |
| **ffmpeg** | **外部终端只读查看**（抓窗口画面） | 无法查看终端内容 | `sudo apt install -y ffmpeg` |
| docker | Docker 模块 | 仅该模块不可用 | 见官方文档 |
| `nvidia-smi` | GPU 监控 | 无 N 卡时属正常 | 显卡驱动自带 |
| pywebview + GUI 后端 | 悬浮小屏 | 小屏不可用 | 见「悬浮小屏」小节 |

服务**运行本身不需要 sudo**；sudo 仅用于安装依赖与配置防火墙。

### 部署产生的配置

`~/.config/deckpit.env`（权限 600，由 setup.sh 生成）：

```bash
DASH_HOST=0.0.0.0
DASH_PORT=8787
DASH_AUTH_USER=admin
DASH_AUTH_PASSWORD=自动生成的强口令
```

## 快速开始

### 环境要求

- Ubuntu 22.04（GNOME 桌面，外部终端控制功能依赖 X11）
- Python 3.11+，Node.js 20+（nvm 管理）
- 可选：NVIDIA 显卡 + 驱动（GPU 监控）、Docker（Docker 模块）、tmux、wmctrl + xdotool（外部终端控制）

### 1. 安装依赖

```bash
# 一键预检 + 自动补齐（推荐新机器先跑这个）
./scripts/check-env.sh            # 检查缺什么，输出 PASS/WARN/FAIL 和安装命令
./scripts/check-env.sh --fix      # 自动补齐 venv / pip 依赖 / 前端 dist（sudo apt 部分需手动）
```

手动安装等价命令：

```bash
# 后端
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 前端
cd ../frontend
npm install
```

### 2. 开发模式

```bash
./scripts/dev.sh
```

同时启动：后端 `uvicorn main:app --reload`（:8787）+ 前端 Vite（:5173，`/api`、`/ws` 已代理到 8787）。
访问 `http://localhost:5173`。

### 3. 生产模式

```bash
./scripts/start.sh
```

构建前端 dist 并由后端静态托管，单端口 `http://localhost:8787` 运行；从其他机器访问请用 `http://<本机内网IP>:8787`（需先设置 `DASH_AUTH_PASSWORD`，见[局域网 / 远程访问](#局域网--远程访问)）。

### 4. 悬浮小屏（可选）

```bash
DASH_PALETTE=1 ./scripts/dev.sh     # 或 start.sh
```

或单独运行：

```bash
python scripts/quickpalette.py
```

快捷键 `Ctrl+Shift+Space` 切换显示（依赖 pynput，可选）。

### 5. 开机自启（systemd user service）

unit 由 `scripts/setup.sh` 第 5 步按实际安装路径生成并写入 `~/.config/systemd/user/deckpit.service`
（路径含空格会自动转义，无需手工修改）：

```bash
./scripts/setup.sh              # 交互式，走到「5. 开机自启」选 Y
DASH_SETUP_YES=1 ./scripts/setup.sh   # 非交互：全部采用推荐默认值
```

常用命令：

```bash
systemctl --user status deckpit
systemctl --user restart deckpit
journalctl --user -u deckpit -f   # 查看日志
```

注销后仍需保持运行（服务器场景）：`sudo loginctl enable-linger $USER`

## 项目结构

```
Deckpit/
├── backend/
│   ├── main.py               # FastAPI 入口：路由注册·预置数据·后台任务·SPA 托管
│   ├── auth.py               #   远程访问认证：按来源判定 + 口令校验 + 会话 + ASGI 中间件
│   ├── config.py             # 全局配置（端口/采样间隔/回滚行数等，环境变量可覆盖）
│   ├── database.py           # SQLite 连接与 14 张表建表迁移
│   ├── routers/              # 10 个 REST 路由模块
│   │   ├── commands.py       #   命令手册 + 终端历史
│   │   ├── files.py          #   文件管理 + 书签/模板/Nautilus 窗口
│   │   ├── ports.py          #   端口/进程/systemd/僵尸/快照
│   │   ├── terminal.py       #   PTY/tmux/外部终端/常用终端/服务运行管理
│   │   ├── system.py         #   系统监控 + GPU 进程 + 依赖安装
│   │   ├── logs.py           #   日志分页/搜索/聚合/告警
│   │   ├── env.py            #   环境探测/.env/CUDA
│   │   ├── ssh.py            #   SSH 主机/远程收藏/config 导入
│   │   ├── dashboard.py      #   首页聚合/项目/一键操作
│   │   ├── docker.py         #   容器/镜像/卷/网络/compose
│   │   └── ai.py             #   AI 会话/配置百科/动作确认
│   ├── services/             # 业务服务
│   │   ├── pty_manager.py    #   PTY 会话池（核心：fork+pty+scrollback 回放）
│   │   ├── monitor_service.py#   psutil/pynvml 采样循环（动态频率）
│   │   ├── port_service.py   #   ss 解析 + /proc inode 反查 + 父进程链
│   │   ├── docker_service.py #   Docker CLI 封装
│   │   ├── external_terminal.py # wmctrl+xdotool 外部终端控制
│   │   ├── history_sync.py   #   shell 历史后台增量同步
│   │   ├── ai/               #   Provider/Catalog/Tools/Actions/Chat
│   │   └── ...               #   env/log/tmux/dependency/file/clipboard
│   ├── ws/                   # 3 个 WebSocket 端点
│   │   ├── terminal_ws.py    #   终端双向桥（重连先回放 scrollback）
│   │   ├── monitor_ws.py     #   监控快照推送（2s 活跃/10s 空闲）
│   │   └── log_ws.py         #   日志 tail + ERROR 告警
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── views/            # 11 个页面视图（含 QuickPalette）
│       ├── components/       # DependencyBanner + ai/（抽屉/消息/动作卡片）
│       ├── stores/           # Pinia（terminal/system/ai）
│       ├── api/              # axios 封装 + WS 客户端 + AI 流式
│       └── router/           # 路由配置
├── scripts/
│   ├── dev.sh               # 开发模式（前后端并行）
│   ├── start.sh             # 生产模式（构建+托管，端口预检）
│   └── quickpalette.py      # 悬浮小屏宿主（pywebview+托盘+吸附）
├── data/
│   └── dashboard.db         # SQLite 数据库
├── PRD-v1.md                # 需求基线（M0–M9，92 条 FR）
└── TECH-PLAN.md             # 技术方案（架构/API/数据模型/风险）
```

## API 概览

REST 前缀：`/api/commands`、`/api/files`、`/api/ports`、`/api/processes`、`/api/systemd`、`/api/terminal`、`/api/system`、`/api/logs`、`/api/env`、`/api/ssh`、`/api/docker`、`/api/dashboard`、`/api/ai`

WebSocket 端点：

| 路径 | 方向 | 说明 |
|------|------|------|
| `/ws/terminal/{session_id}` | 双向 | 终端 stdin/stdout；重连首帧为 scrollback 回放 |
| `/ws/system/monitor` | 服务端推 | 监控快照，默认 2s 一帧 |
| `/ws/logs/tail?path=` | 服务端推 | 日志增量，检测到 ERROR 触发告警 |

启动后访问 `http://localhost:8787/docs` 查看完整 OpenAPI 文档。

## 配置

后端配置集中在 `backend/config.py`，均可通过环境变量覆盖，关键项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | `8787` | 服务端口 |
| `MONITOR_INTERVAL` | `2.0s` | 活跃时监控采样间隔 |
| `PTY_SCROLLBACK_LINES` | `5000` | 终端回滚缓冲行数 |
| `PTY_MAX_SESSIONS` | `20` | 最大并发终端会话数 |
| `HISTORY_SYNC_INTERVAL` | `5.0s` | shell 历史同步间隔 |
| `DISK_ALERT_THRESHOLD` | `0.90` | 磁盘使用率预警阈值 |
| `DASH_AI_ENABLED` | `1` | AI 助手总开关 |
| `DASH_AI_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible 模型地址 |
| `DASH_AI_MODEL` | 空 | 模型名，如 `qwen2.5:14b` |
| `DASH_AI_API_KEY` | 空 | 云端模型 Key（也可在页面设置里填，服务端加密） |
| `DASH_AI_TIMEOUT` | `120` | 模型请求超时（秒） |
| `DASH_AI_CONTEXT_BUDGET` | `32000` | 估算 token 预算；本地 8k 模型请调小 |
| `DASH_AI_ALLOW_CLOUD` | `0` | 是否允许公网模型地址 |
| `DASH_AI_ACTION_MODE` | `confirm_all` | 动作确认策略 |

环境变量名统一带 `DASH_` 前缀（如 `DASH_HISTORY_SYNC_INTERVAL`），上表列的是 `config.py` 里的常量名。

### AI 助手配置

1. 本地模型（推荐）：先启动 Ollama / vLLM，确认有 OpenAI-compatible 的 `/v1` 接口。
2. 在 `~/.config/deckpit.env` 或页面「AI 助手 → 设置」里填：

```bash
DASH_AI_BASE_URL=http://127.0.0.1:11434/v1
DASH_AI_MODEL=qwen2.5:14b
# 云端才需要：
# DASH_AI_API_KEY=...
# DASH_AI_ALLOW_CLOUD=1
```

3. 重启后端，打开页面点侧边栏「AI 助手」，或按 `Alt+A`。
4. 设置页有「测试连接」；没有模型时可用 `DASH_AI_PROVIDER=mock` 做 UI 联调（Mock 不会执行任何动作）。

AI 的能力边界：只查询已配置信息 + 对已有服务/容器/Compose 提议启停；不执行任意命令、不读写文件、不 kill 进程、不做 SSH 远端操作。所有动作都需要前端确认，并写入 `ai_actions` 审计表。

本地验收：

```bash
cd backend && .venv/bin/python -m pytest -q
cd ../frontend && npm run build
```

## 局域网 / 远程访问

默认监听 `0.0.0.0:8787`，但**认证策略区分来源**：

| 访问来源 | 是否需要登录 |
|----------|--------------|
| 服务端本机（`127.0.0.1` / `::1`） | 免登录，与以前完全一致 |
| 其他机器（局域网 / 公网） | 必须账号密码登录 |

### 开启远程登录

```bash
DASH_AUTH_PASSWORD='你的强密码' ./scripts/run-prod.sh
# 自定义用户名：DASH_AUTH_USER=dev DASH_AUTH_PASSWORD=xxx ./scripts/run-prod.sh
# 不想用明文：DASH_AUTH_PASSWORD_HASH=$(echo -n '密码' | sha256sum | awk '{print $1}')
```

启动后会打印可访问地址：

```
监听: 0.0.0.0:8787
本机访问: http://localhost:8787
局域网访问: http://192.168.0.159:8787
```

**未设置口令时，非本机访问一律返回 403（fail-closed）**，不会出现"已开放但无口令"的窗口期。

只想退回纯本机访问：

```bash
DASH_HOST=127.0.0.1 ./scripts/run-prod.sh
```

### 防火墙（建议只放行内网段）

```bash
sudo ufw allow from 192.168.0.0/24 to any port 8787   # 仅局域网段
sudo ufw status
```

### 相关配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DASH_HOST` | `0.0.0.0` | 监听地址 |
| `DASH_AUTH_USER` | `admin` | 登录用户名 |
| `DASH_AUTH_PASSWORD` | 空 | 登录口令（空 = 拒绝非本机访问） |
| `DASH_AUTH_PASSWORD_HASH` | 空 | 口令的 sha256 摘要，优先级高于上一项 |
| `DASH_AUTH_SESSION_TTL` | `43200` | 会话有效期（秒） |
| `DASH_AUTH_LOCAL_BYPASS` | `1` | 本机来源免登录，置 `0` 则本机也要登录 |
| `DASH_AUTH_MAX_FAILS` | `5` | 同一来源连续失败上限，超出锁定 |
| `DASH_AUTH_LOCK_SECONDS` | `300` | 触发失败上限后的锁定时长（秒） |
| `DASH_TRUST_PROXY` | `0` | 用 `X-Forwarded-For` 判定来源；仅挂可信反代时置 `1` |

说明与限制：

- 会话保存在**服务端内存**，服务重启后所有远程客户端需重新登录。
- 认证 Cookie 为 `HttpOnly` + `SameSite=Lax`，前端静态资源放行以便未登录时能渲染登录页；真正受保护的是 `/api/*`（除 `/api/auth/*`）、`/ws/*`、`/docs`、`/openapi.json`。
- 未登录的 WebSocket 握手会被以 `1008` 关闭，前端据此停止重连并跳转登录页。
- `DASH_TRUST_PROXY=1` 时伪造 `X-Forwarded-For: 127.0.0.1` 即可绕过认证，**仅在你确实挂了可信反向代理时才开启**（开发模式由 `scripts/dev.sh` 自动开启，因为请求经 Vite 代理转发，后端本身仍只监听 `127.0.0.1`）。
- 传输为明文 HTTP，跨公网使用请在前面套一层 HTTPS 反向代理。

## 让终端命令实时进入历史

四个来源都会自动收录进「终端历史」，且**同一条命令只保留一行**——重复执行不会堆出重复行，而是把它的时间戳刷新为最新、排到历史最前面（时间戳为毫秒精度，同秒连敲也能正确排序）。

| 来源 | 是否实时 | 需要设置 |
|------|----------|----------|
| 面板内终端（Dashboard 自带 PTY） | 实时，回车即上报 | 无 |
| 外部终端「发送命令」按钮 | 实时 | 无 |
| 命令手册「发送」 | 实时 | 无 |
| 外部终端里手敲的命令 | 后台增量同步历史文件 | 见下 |

前三者由前端在命令提交时直接调 `POST /commands/history`。外部终端里手敲的命令只能从 shell 历史文件里同步，而 **bash 默认只在 shell 退出时才写 `~/.bash_history`**，所以必须让 shell 每条命令执行后立即落盘：

```bash
# ~/.bashrc
shopt -s histappend
PROMPT_COMMAND="history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
```

```zsh
# ~/.zshrc
setopt INC_APPEND_HISTORY      # 每条命令执行后立即写入；共享多终端可用 SHARE_HISTORY
```

之后后台任务会按 `DASH_HISTORY_SYNC_INTERVAL`（默认 5 秒）增量读取，想更接近实时就调小：

```bash
DASH_HISTORY_SYNC_INTERVAL=1 ./scripts/start.sh        # 1 秒一轮
DASH_HISTORY_GLOBAL=1 ./scripts/start.sh               # 顺带同步 /home/* 下其他用户的历史（需有读权限）
DASH_HISTORY_MAX_ENTRIES=500 ./scripts/start.sh        # 首次遇到某历史文件时最多导入多少条
```

说明：

- 只读取 `~/.bash_history` / `~/.zsh_history`（`HISTORY_GLOBAL=1` 时扩展为 `/home/*`）；自定义 `HISTFILE` 不在此列。
- 若设置了 `HISTTIMEFORMAT`，bash 会写入 `#<epoch>` 时间戳行，这类行会被忽略，不会被当成命令收录。
- 同步进度（每个历史文件的字节偏移）存在 `settings` 表里，重启服务后会接着上次位置继续，离线期间敲的命令也会补录。

## 外部终端接管（远程操作服务器上的终端）

「终端中心 → 外部终端」列出的窗口属于**服务器桌面（X11）**，聚焦/关闭只在服务器端生效，远程浏览器看不到画面。要在远程机器上操作它们，用「**接管到浮窗**」：

### 只读查看（任何终端都能用，包括正在跑服务的）

定时抓取该窗口画面（ffmpeg `x11grab`）显示在浏览器浮窗里：**能看到里面的真实内容，但不能发送任何指令**。刷新频率可选 1 / 2 / 5 秒或暂停，也可拖动和最大化。

这是唯一能"看到"一个已在运行的终端里内容的通用办法 —— 已存在终端的输出流无法事后读取（pty 的消费者唯一），终端模拟器也不对外提供滚动缓冲区。

限制：只能看到**当前可见的一屏**，拿不到已滚出屏幕的历史；窗口被遮挡时会先把它提到最前再抓。依赖 `ffmpeg`。

### 接管（可双向操作，有条件）

要让浮窗里的终端**能输入**，用「接管到浮窗」，前提是 `tmux`：

1. 该终端此前被接管过 → 直接复用其 tmux 会话（不会反复嵌套注入）；
2. 该终端的 shell 本来就在 tmux 里 → 直接 attach，能看到它的完整回滚；
3. 否则向该窗口注入 `exec tmux new-session -A -s deckpit-w<窗口XID>`，把当前 shell 挂进 tmux，再在浏览器浮窗里 attach。

接管后是一个可拖动 / 可最大化 / 可缩放的浏览器浮窗，**双向实时同步**：服务器上那个终端的输入输出，和你在这里敲的完全一致。关闭浮窗不会终止会话，可在终端中心找回。

已知边界：

- **接管之前的输出不会带过来**（新的 tmux pane 从接管时刻开始）；要包含已有历史，那个终端必须本来就在 tmux 里。
- 终端前台正在跑程序（vim / top / 交互程序）时注入的命令会被它当输入吞掉，接管会超时失败 —— 请先回到 shell 提示符。
- GNOME Terminal 属于"单进程多窗口"终端，所有窗口共享一个 `gnome-terminal-server` 进程，因此**无法提前判断目标窗口是否空闲**，只能尝试注入并按超时判定成败；会话按窗口 XID（而非 PID）命名，避免多个窗口串台。
- 依赖服务器安装 tmux：`sudo apt install tmux`。

## 安全设计

- 默认不暴露外网；无遥测、无外网回调
- 认证按来源区分：本机免登录，非本机必须账号密码（详见[局域网 / 远程访问](#局域网--远程访问)）
- 未配置 `DASH_AUTH_PASSWORD` 时非本机访问直接拒绝，登录失败超限自动锁定来源
- 危险操作（kill 进程、删除文件、覆盖写入）一律要求前端二次确认
- kill 默认 SIGTERM，SIGKILL 需显式选择；展示完整 cmdline 防误杀
- 文件操作经 `Path.resolve()` 前缀校验，拒绝 `..` 与符号链接逃逸
- `.env` 敏感值展示默认打码
- AI 动作只接受“目标 ID + 白名单动作”，不接受模型生成的 shell 命令；动作必须前端确认，并写入 `ai_actions` 审计
- AI 上下文不含 SSH 密码、`.env` 原值、Provider Key；模型只能查询配置和对已有对象提议启停

## 已知限制

- 外部终端窗口控制（wmctrl/xdotool）与悬浮小屏吸附依赖 X11，Wayland 下不可用
- GPU 监控仅支持 NVIDIA（pynvml / nvidia-smi）
- 远程主机管理未做——SSH 模块仅"发起连接"，不是远端面板
- systemd 用户服务需由 `scripts/setup.sh` 安装（它会按实际路径生成 unit）；手动迁移目录后需重跑 setup
- 远程登录会话保存在服务端内存，服务重启后远程客户端需重新登录
- AI 助手需要单独配置模型；未配置时入口可用但只提示“未配置模型”，不影响主应用
- 服务运行状态保存在后端内存，后端重启后需重新查询/启动；AI 回答会标注状态来源
- 如果服务端口在监听但不是面板启动的进程，AI 会拒绝 stop/restart（无法安全接管外部进程）
- AI 的 Compose 动作用 `stop` 而不是 `down`（避免移除容器）；不会执行 `rm` / `prune` / `kill`
- AI 会话、动作审计保存在 SQLite；模型上下文里不含 SSH 密码、`.env` 原值和 API Key

## 文档

- [PRD-v1.md](PRD-v1.md) — 需求基线：M0–M9 模块、92 条 FR、优先级与里程碑
- [TECH-PLAN.md](TECH-PLAN.md) — 技术方案：选型决策、架构、API 设计、数据模型、风险应对
