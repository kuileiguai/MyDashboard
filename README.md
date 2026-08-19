# Deckpit — 自建 Linux 开发者工作台

> **Deckpit** = Deck（甲板/卡片面板）+ Cockpit（驾驶舱）——一块卡片式面板，当你的开发驾驶舱。

一个运行在 `http://localhost:8787` 的本地 Web 工作台，把开发者日常高频操作——**命令速查、文件管理、端口/进程、终端、系统监控、日志、环境、SSH、Docker**——统一到一个页面里：可看、可搜、可点、可拖。

面向单用户（开发者本人），基准环境 **Ubuntu 22.04 + GNOME**，仅监听 `127.0.0.1`，零外网依赖。

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
- **自动吸附**：检测到你在用终端时贴其右缘显示，切走自动隐藏
- 全局快捷键 `Ctrl+Shift+Space` 唤起，系统托盘常驻；支持"点即发送到活动终端"

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 + FastAPI + Uvicorn + aiosqlite |
| 前端 | Vue 3 + Vite + Element Plus + Pinia + Vue Router |
| 终端 | xterm.js + Python `pty`（fork + PTY 池管理） |
| 图表 | ECharts (vue-echarts) |
| 实时通信 | WebSocket（终端 I/O / 监控推送 / 日志 tail 三通道） |
| 系统采集 | psutil + pynvml + `ss` / `/proc` 解析 |
| 桌面集成 | wmctrl + xdotool + pywebview（悬浮小屏） |
| 存储 | SQLite 单文件（14 张表） |
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

## 快速开始

### 环境要求

- Ubuntu 22.04（GNOME 桌面，外部终端控制功能依赖 X11）
- Python 3.11+，Node.js 20+（nvm 管理）
- 可选：NVIDIA 显卡 + 驱动（GPU 监控）、Docker（Docker 模块）、tmux、wmctrl + xdotool（外部终端控制）

### 1. 安装依赖

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

构建前端 dist 并由后端静态托管，单端口 `http://localhost:8787` 运行。

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

```bash
mkdir -p ~/.config/systemd/user
cp deploy/deckpit.service ~/.config/systemd/user/
# 按实际安装路径修改 unit 文件中的 WorkingDirectory
systemctl --user daemon-reload
systemctl --user enable --now deckpit
journalctl --user -u deckpit -f   # 查看日志
```

## 项目结构

```
Deckpit/
├── backend/
│   ├── main.py               # FastAPI 入口：路由注册·预置数据·后台任务·SPA 托管
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
│   │   └── docker.py         #   容器/镜像/卷/网络/compose
│   ├── services/             # 12 个业务服务
│   │   ├── pty_manager.py    #   PTY 会话池（核心：fork+pty+scrollback 回放）
│   │   ├── monitor_service.py#   psutil/pynvml 采样循环（动态频率）
│   │   ├── port_service.py   #   ss 解析 + /proc inode 反查 + 父进程链
│   │   ├── docker_service.py #   Docker CLI 封装
│   │   ├── external_terminal.py # wmctrl+xdotool 外部终端控制
│   │   ├── history_sync.py   #   shell 历史后台增量同步
│   │   └── ...               #   env/log/tmux/dependency/file/clipboard
│   ├── ws/                   # 3 个 WebSocket 端点
│   │   ├── terminal_ws.py    #   终端双向桥（重连先回放 scrollback）
│   │   ├── monitor_ws.py     #   监控快照推送（2s 活跃/10s 空闲）
│   │   └── log_ws.py         #   日志 tail + ERROR 告警
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── views/            # 11 个页面视图（含 QuickPalette）
│       ├── components/       # DependencyBanner 等公共组件
│       ├── stores/           # Pinia（terminal/system）
│       ├── api/              # axios 封装 + WS 客户端（自动重连/心跳）
│       └── router/           # 路由配置
├── scripts/
│   ├── dev.sh               # 开发模式（前后端并行）
│   ├── start.sh             # 生产模式（构建+托管，端口预检）
│   └── quickpalette.py      # 悬浮小屏宿主（pywebview+托盘+吸附）
├── deploy/
│   └── deckpit.service       # systemd 用户服务单元
├── data/
│   └── dashboard.db         # SQLite 数据库
├── PRD-v1.md                # 需求基线（M0–M9，92 条 FR）
└── TECH-PLAN.md             # 技术方案（架构/API/数据模型/风险）
```

## API 概览

REST 前缀：`/api/commands`、`/api/files`、`/api/ports`、`/api/processes`、`/api/systemd`、`/api/terminal`、`/api/system`、`/api/logs`、`/api/env`、`/api/ssh`、`/api/docker`、`/api/dashboard`

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

## 安全设计

- 仅绑定 `127.0.0.1`，不暴露外网；无遥测、无外网回调
- 危险操作（kill 进程、删除文件、覆盖写入）一律要求前端二次确认
- kill 默认 SIGTERM，SIGKILL 需显式选择；展示完整 cmdline 防误杀
- 文件操作经 `Path.resolve()` 前缀校验，拒绝 `..` 与符号链接逃逸
- `.env` 敏感值展示默认打码

## 已知限制

- 外部终端窗口控制（wmctrl/xdotool）与悬浮小屏吸附依赖 X11，Wayland 下不可用
- GPU 监控仅支持 NVIDIA（pynvml / nvidia-smi）
- 远程主机管理未做——SSH 模块仅"发起连接"，不是远端面板
- systemd 服务单元中的工作目录需按实际安装路径修改

## 文档

- [PRD-v1.md](PRD-v1.md) — 需求基线：M0–M9 模块、92 条 FR、优先级与里程碑
- [TECH-PLAN.md](TECH-PLAN.md) — 技术方案：选型决策、架构、API 设计、数据模型、风险应对
