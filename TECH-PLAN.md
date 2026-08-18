# 自建 Linux 开发者 Dashboard — 技术方案 v1.0

> 配套文档：`PRD-v1.md`（需求基线，M0–M9 共 92 条 FR）。本文档回答"怎么实现"，需求口径以 PRD-v1 为准。

---

## 1. 技术选型决策

| 层 | 决策 | 理由 | 备选 |
|----|------|------|------|
| 后端 | Python 3.11 + FastAPI | 与 AI 开发同语言；系统调用生态最全（psutil/subprocess/pynvml）；AI 生成 Python 代码质量最高 | Node + Express |
| ASGI | Uvicorn | FastAPI 标配，原生 WebSocket | — |
| 前端 | Vue 3 + Vite + Element Plus | 组件全（表格/标签页/树/拖拽），上手快，天然适合 Dashboard | React + AntD |
| 状态管理 | Pinia | Vue3 官方 | — |
| 内嵌终端 | xterm.js + Python `pty` | 浏览器渲染真实终端；后端 PTY 池管理会话 | node-pty |
| 实时通信 | WebSocket（FastAPI 原生） | 终端 I/O、监控推送、日志 tail 统一走 WS | SSE（仅监控够用，终端不行） |
| 系统信息采集 | psutil + 解析 `ss`/`/proc` | 跨发行版稳定 | 纯 /proc 解析 |
| GPU 采集 | pynvml（优先），fallback 解析 `nvidia-smi` 输出 | pynvml 无子进程开销，适合 2s 轮询 | — |
| 数据库 | SQLite（标准库 `sqlite3` 或 SQLModel） | 单文件、零运维、够用 | JSON 文件 |
| 运行方式 | 本地服务 + 浏览器访问 `http://localhost:8080` | 最轻量 | 后期可套 Tauri 壳 |
| 部署 | venv + systemd user service | 开机自启、崩溃自动重启 | pm2 / supervisor |

**为什么不用 Electron**：Ubuntu 上浏览器开 localhost 即可，省几百 MB 内存；后期真要桌面窗口再套 Tauri。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────┐
│  浏览器 (http://localhost:8080)                      │
│  Vue3 SPA ── Element Plus ── xterm.js ── ECharts    │
└──────┬───────────────────────┬──────────────────────┘
       │ REST (JSON)           │ WebSocket
       ▼                       ▼
┌─────────────────────────────────────────────────────┐
│  FastAPI (uvicorn, :8080)                            │
│  ├─ routers/    commands/files/ports/terminal/...    │
│  ├─ services/   业务逻辑（端口解析、PTY池、监控采样）  │
│  ├─ ws/         终端桥接 / 监控推送 / 日志tail        │
│  └─ models/     SQLite (命令/书签/SSH/设置/统计)      │
└──────┬───────────┬─────────────┬────────────────────┘
       │           │             │
       ▼           ▼             ▼
   psutil/     pty +         subprocess
   /proc/      subprocess    (ss, nvidia-smi,
   sqlite      (bash/zsh)    docker, git, ...)
```

**三类数据流**：
1. **请求-响应**（REST）：CRUD 类——命令、书签、SSH 主机、文件操作、端口查询。
2. **服务端推送**（WS）：监控指标（2s）、日志 tail、终端 stdout。
3. **双向**（WS）：终端 stdin/stdout。

---

## 3. 项目结构

```
linux-dashboard/
├── backend/
│   ├── main.py                  # FastAPI 入口、CORS、路由注册、静态托管前端dist
│   ├── config.py                # 端口/路径/采样间隔等配置
│   ├── database.py              # SQLite 连接与建表
│   ├── routers/
│   │   ├── commands.py          # M1
│   │   ├── files.py             # M2
│   │   ├── ports.py             # M3
│   │   ├── terminal.py          # M4 REST 部分
│   │   ├── system.py            # M5
│   │   ├── logs.py              # M6
│   │   ├── env.py               # M7
│   │   ├── ssh.py               # M8
│   │   └── dashboard.py         # M9 聚合接口
│   ├── services/
│   │   ├── port_service.py      # ss 解析 + /proc  enrichment
│   │   ├── pty_manager.py       # PTY 会话池（核心）
│   │   ├── monitor_service.py   # psutil/pynvml 采样循环
│   │   ├── log_service.py       # 分页读取 + tail watcher
│   │   ├── file_service.py      # 文件操作 + 安全校验
│   │   └── env_service.py       # venv/conda/nvm 探测
│   ├── ws/
│   │   ├── terminal_ws.py       # WS <-> PTY 双向桥
│   │   ├── monitor_ws.py        # 监控推送
│   │   └── log_ws.py            # 日志 tail 推送
│   ├── models/                  # SQLModel/SQLite 表定义
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/               # 每模块一页: Commands/Files/Ports/Terminal/System/Logs/Env/Ssh/Home
│   │   ├── components/          # TerminalTab/PortTable/LogViewer/MonitorChart...
│   │   ├── stores/              # Pinia: terminal/command/system/...
│   │   ├── api/                 # axios 封装 + ws client 封装（自动重连）
│   │   └── router/
│   ├── package.json
│   └── vite.config.ts           # 开发代理 /api 与 /ws -> 8080
├── scripts/
│   ├── dev.sh                   # 同时起前后端（开发）
│   └── start.sh                 # 生产启动（uvicorn 托管前端 dist）
├── deploy/
│   └── dev-dash.service         # systemd user unit
└── README.md
```

---

## 4. 后端设计要点

### 4.1 PTY 管理器（M4 核心，`pty_manager.py`）

```python
# 核心思路
class PtySession:
    session_id: str
    name: str
    cwd: str
    process: subprocess.Popen   # bash, stdin/stdout 接 pty
    master_fd: int              # os.openpty() 的主端
    scrollback: deque           # 回滚缓冲（默认保留最近 ~5000 行）
    last_output_at: datetime    # 状态灯用（黄=有输出）

class PtyManager:
    sessions: dict[str, PtySession]
    def create(name, cwd, shell, init_cmd) -> session_id
    def write(session_id, data)          # stdin
    def read_loop(session_id, ws)        # master_fd -> WS（asyncio 挂 reader）
    def resize(session_id, rows, cols)   # fcntl.ioctl TIOCSWINSZ
    def kill(session_id)
    def reattach(session_id, ws)         # 重连：先补发 scrollback，再接实时流
```

关键点：
- **会话持久化（M4-F8）**：PTY 进程活在后端，前端断开不影响；WS 重连后先回放 `scrollback` 再接实时流。
- 状态灯（M4-F3）：`last_output_at` 距现在 <2s → 黄灯。
- 关闭页面 ≠ 关闭终端；"关闭标签"才 kill。

### 4.2 端口采集（M3，`port_service.py`）

```
ss -tlnp  →  解析得 (proto, port, pid)
/proc/{pid}/cmdline  →  启动命令
/proc/{pid}/cwd      →  工作目录（readlink）
psutil.Process(pid)  →  进程名/启动时间/用户/parents() 父进程链
```
- 注意权限：非本用户进程的部分字段可能拿不到，返回 `null` 而非报错。
- kill（M3-F4）：先 `SIGTERM`，前端提供"强制 kill"再发 `SIGKILL`。

### 4.3 监控采样（M5，`monitor_service.py`）

- 一个 asyncio 后台任务，每 2s 采样一次，写入内存环形缓冲（deque, 150 个点 = 5 分钟）。
- CPU/内存/磁盘/网络：`psutil`（`cpu_percent(percpu=True)`、`virtual_memory`、`disk_io_counters`、`net_io_counters`，速率=差分/间隔）。
- GPU：`pynvml` 取 `nvmlDeviceGetMemoryInfo/UtilizationRates/Temperature/PowerDraw/FanSpeed` + `nvmlDeviceGetComputeRunningProcesses`；`ImportError`/无卡时整个 GPU 区块返回 `available: false`，前端隐藏。
- WS 推送：每 2s 推一帧全量快照；无订阅时采样任务降频到 10s 省电。

### 4.4 大日志读取（M6，`log_service.py`）

- 分页：`offset/limit` 按字节 seek 读取，向前对齐到行边界。
- tail：`watchdog` 或 1s 轮询文件 size/mtime，增量部分经 WS 推送。
- 搜索（M6-F5）：后端逐行正则流式扫描，只回传匹配行 + 行号（不把整文件灌给前端）。

### 4.5 安全边界

- 仅绑定 `127.0.0.1`。
- 文件操作（M2）限制在允许根目录集合内（默认 `$HOME`），拒绝 `..` 逃逸与符号链接逃逸（`Path.resolve()` 后校验前缀）。
- kill/删除/覆盖 一律要求前端二次确认参数 `confirm: true`。
- 不做任何外网回调；无遥测。

---

## 5. 前端设计要点

- **布局**（M0-F3）：`el-aside` 可折叠导航 + `router-view`；终端中心页内部自带标签栏。
- **终端组件**：xterm.js + `@xterm/addon-fit`（自适应）+ `@xterm/addon-web-links`；WS 二进制/文本直通。
- **图表**：ECharts 折线图（CPU/内存/GPU/网络），数据来自 WS 推送的环形缓冲。
- **文件管理器**：左侧 `el-tree` + 右侧 `el-table` + 顶部面包屑；拖拽用 HTML5 DnD。
- **虚拟滚动**（M6-F2）：日志区用 `vue-virtual-scroller` 或自实现行窗口。
- **主题**（M0-F4）：CSS 变量 + `prefers-color-scheme` 默认值，手动覆盖存 localStorage。
- **WS 封装**：统一 client，含指数退避重连、心跳 ping、按 topic 订阅。

---

## 6. API 汇总

### REST

| 模块 | 方法与路径 | 说明 |
|------|-----------|------|
| M1 | `GET /api/commands?keyword=&category=` | 命令搜索/列表 |
| M1 | `POST /api/commands` / `PUT /api/commands/{id}` / `DELETE /api/commands/{id}` | CRUD |
| M1 | `POST /api/commands/{id}/favorite` | 收藏切换 |
| M1 | `GET /api/commands/history?favorite=&q=&limit=` | 终端历史（含全局 shell 同步记录，支持常用/关键字过滤） |
| M1 | `POST /api/commands/history/{id}/favorite` | 历史记录加常用切换 |
| M1 | `GET /api/commands/lookup?q=&limit=` | 聚合手册+历史模糊查找（悬浮小屏用） |
| M2 | `GET /api/files?path=` | 目录列表 |
| M2 | `POST /api/files/mkdir` / `touch` / `rename` / `copy` / `move` | 文件操作 |
| M2 | `DELETE /api/files` | 删除（confirm 参数） |
| M2 | `GET/POST /api/files/bookmarks` / `DELETE /api/files/bookmarks/{id}` | 快捷位置 |
| M3 | `GET /api/ports` | 全部监听端口 |
| M3 | `GET /api/ports/{port}/detail` | 端口详情（含父进程链） |
| M3 | `DELETE /api/ports/{pid}/kill?sig=term|kill` | 结束进程 |
| M3 | `GET /api/processes?sort=cpu|mem&q=` | 全量进程（M3-F7） |
| M4 | `POST /api/terminal/create` `{name, cwd, shell, command}` | 新建 PTY |
| M4 | `GET /api/terminal/list` | 会话列表 |
| M4 | `PUT /api/terminal/{id}/rename` `{name}` | 命名 |
| M4 | `POST /api/terminal/{id}/resize` `{rows, cols}` | 调整大小 |
| M4 | `DELETE /api/terminal/{id}` | 关闭 |
| M4 | `POST /api/terminal/active/send` `{command}` | 发送命令到当前活动终端（悬浮小屏"点即执行"） |
| M5 | `GET /api/system/overview` | 一次性全量指标 |
| M5 | `GET /api/system/disk-top?path=&n=10` | 大文件 Top（M5-F8） |
| M6 | `GET /api/logs?path=&offset=&limit=` | 分页读取 |
| M6 | `GET /api/logs/search?path=&pattern=` | 正则搜索 |
| M7 | `GET /api/env/list` | 环境列表 |
| M7 | `GET /api/env/{name}/packages?type=pip|conda` | 包列表 |
| M7 | `GET /api/env/{name}/requirements` | 导出 txt |
| M7 | `GET /api/env/compare?env1=&env2=` | 环境对比 |
| M8 | `GET/POST /api/ssh/hosts` / `PUT/DELETE /api/ssh/hosts/{id}` | SSH 主机 CRUD |
| M8 | `POST /api/ssh/hosts/{id}/connect` → `{terminal_id}` | 一键连接（联动 M4） |
| M8 | `GET /api/ssh/hosts/{id}/status` | 在线状态 |
| M9 | `GET /api/dashboard/summary` | 首页聚合（概览+活跃终端+最近文件） |

### WebSocket

| 路径 | 方向 | 说明 |
|------|------|------|
| `/ws/terminal/{id}` | 双向 | 终端 stdin/stdout；重连首帧为 scrollback 回放 |
| `/ws/system/monitor` | 服务端推 | 监控快照，默认 2s 一帧 |
| `/ws/logs/tail?path=` | 服务端推 | 日志增量 |

### 命令条目数据结构（M1）

```json
{
  "id": 1,
  "category": "网络",
  "command": "ss -tlnp | grep :8080",
  "description": "查看 8080 端口的监听情况",
  "params": [{"flag": "-t", "meaning": "仅显示TCP"}],
  "examples": ["ss -tlnp", "ss -tlnp | grep :80"],
  "is_favorite": false,
  "use_count": 0
}
```

---

## 7. 数据模型（SQLite）

```sql
commands(id, category, command, description, params_json, examples_json,
         is_favorite, use_count, created_at, updated_at)
bookmarks(id, name, path, sort_order, created_at)
ssh_hosts(id, name, host, port, username, key_path, jump_host, created_at)
terminal_meta(session_id, name, cwd, group_name, sort_order, created_at)  -- 仅元数据，进程在内存
settings(key, value)          -- 主题/采样间隔/常用端口清单/阈值等
usage_stats(id, action, ref_id, created_at)   -- 复制/执行统计（M1-F11）
recent_files(id, path, opened_at)             -- M2-F9
```

---

## 8. 关键技术点与风险

| 风险 | 应对 |
|------|------|
| PTY 会话泄漏（标签关了进程没杀） | PtyManager 统一持有；kill 时 `process.terminate()` + 关 fd；后端退出时全部清理 |
| 前端刷新后终端状态错乱 | WS 重连协议：首帧 scrollback 回放 + 当前 cwd 上报 |
| `ss -tlnp` 权限不足看不到 pid | fallback 到 `/proc/net/tcp` 自行解析 + inode→pid 反查（扫 `/proc/*/fd`） |
| 无 N 卡机器 GPU 区块崩溃 | pynvml import 包 try；接口返回 `available:false`，前端隐藏区块 |
| 大日志文件把内存读爆 | 全程字节 seek 分页；禁止整文件 read |
| kill 误杀 | 前端二次确认 + 展示完整 cmdline + 默认 SIGTERM |
| 文件操作越权 | 根目录白名单 + resolve 后前缀校验 |
| 监控后台任务空转耗电 | 无 WS 订阅时采样降频到 10s |

---

## 9. 部署与运维

**开发模式**：`scripts/dev.sh` = `uvicorn main:app --reload --port 8080` + `vite`（5173，代理 `/api`、`/ws` 到 8080）。

**生产模式**：前端 `vite build` → 后端 FastAPI 静态托管 `dist/`，只跑 8080 一个端口。

**systemd user service**（`deploy/dev-dash.service`）：

```ini
[Unit]
Description=Dev Dashboard
After=default.target

[Service]
WorkingDirectory=%h/linux-dashboard/backend
ExecStart=%h/linux-dashboard/backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

启用：`systemctl --user enable --now dev-dash`；日志：`journalctl --user -u dev-dash -f`。

---

## 10. 实施路线图

> 与 PRD-v1 第 5 节一致。每个 Phase 结束都应是"可用"状态。

| Phase | 内容 | 交付物 | 验收 |
|-------|------|--------|------|
| 0 | M0 P0：双端骨架 | 可打开页面、导航切换、SQLite 初始化 | 页面跑起来 |
| 1 | M4 P0：终端中心 | 多标签 PTY、命名、状态灯、持久化 | 开3个标签命名后刷新仍在 |
| 2 | M3 P0：端口监控 | 表格/搜索/详情/kill/自刷 | 找到 :8000 并 kill 成功 |
| 3 | M1 P0：命令手册 | 预置库/搜索/收藏/CRUD/复制 | 搜"端口"出结果可复制 |
| 4 | M5 P0：系统监控 | CPU/内存/GPU 曲线 | GPU 图实时跳动 |
| 5 | M2 P1：文件管理器 | 树/列表/操作/书签/右键 | 面板内建文件、拖文件到书签 |
| 6 | M6 P1：日志查看 | 大文件/tail/搜索/过滤 | 打开 100MB 日志不卡 |
| 7 | M9 P1 + 各模块 P1 | 首页、分屏、侧边栏、高亮等 | 首页聚合可用 |
| 8 | M7 + M8 | 环境管理、SSH 管理 | 一键 ssh 到测试机 |
| 9 | P2 按需 | tmux/聚合日志/项目概念/快照等 | 按实际需要挑选 |

---

## 11. AI 辅助开发 Prompt 策略

> 沿用 run.md 的原则：**分模块喂，不要一次让 AI 全写完**。每个模块一段自包含 prompt。

**每个模块的 prompt 模板**：

```
背景：Ubuntu 22.04 本地开发 Dashboard，FastAPI(8080) + Vue3/Vite/Element Plus(5173) + SQLite。
项目结构：<粘贴第3节相关子树>
已完成：<列出已完成模块的接口/组件>
本模块需求：<从 PRD-v1 粘贴该模块 FR 表 + 关键 AC>
接口约定：<从第6节粘贴该模块 API>
要求：后端 routers/xxx.py + services/xxx.py；前端 views/XxxView.vue + api/xxx.js；
     给出完整可运行代码，不要省略错误处理。
```

**推荐顺序**（同第 10 节 Phase 0→9）：框架 → 终端中心 → 端口监控 → 命令手册 → 系统监控 → 文件管理 → 日志 → 首页 → 环境/SSH。

**注意事项**：
- 终端中心 prompt 里必须附上 4.1 节的 PtyManager 设计，否则 AI 容易写出"前端断开就杀进程"的版本。
- 端口模块 prompt 里附上 4.2 节解析链路，避免 AI 只用 `lsof`（解析脆弱）。
- 每个 Phase 完成后人工验收对应 AC，再开下一个 prompt。

---

## 12. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-08-11 | 初版：合并 PRD.md 与 run.md 的技术内容，补齐 PTY 管理器/端口解析/监控采样/大日志读取四大关键设计与风险表 |
