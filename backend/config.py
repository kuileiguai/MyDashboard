"""全局配置"""

import os
from pathlib import Path

# 服务器
HOST = os.environ.get("DASH_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASH_PORT", "8787"))

# 数据库
DB_DIR = Path(os.environ.get("DASH_DATA_DIR", str(Path(__file__).parent.parent / "data")))
DB_PATH = DB_DIR / "dashboard.db"

# 采样
MONITOR_INTERVAL = float(os.environ.get("DASH_MONITOR_INTERVAL", "2.0"))      # 活跃采样间隔 (s)
MONITOR_IDLE_INTERVAL = float(os.environ.get("DASH_MONITOR_IDLE_INTERVAL", "10.0"))  # 无订阅时降频 (s)
MONITOR_HISTORY_POINTS = 150  # 5 分钟 @ 2s

# PTY
PTY_SCROLLBACK_LINES = 5000
PTY_MAX_SESSIONS = 20

# 安全
ALLOWED_ROOTS = [Path("/")]  # 默认全文件系统可访问，单用户本地环境无需限制
DISK_ALERT_THRESHOLD = 0.90  # 90% 预警

# 日志
LOG_DIR = DB_DIR / "logs"

# Docker：当前用户无 docker 组权限、且不想改用户组/重新登录时，
# 设为 "1" 让后端调用 docker 时自动加 `sudo -n`（非交互，需 sudo NOPASSWD 或已缓存凭证）。
DOCKER_SUDO = os.environ.get("DASH_DOCKER_SUDO", "0") == "1"

# shell 历史自动同步（全局指令收录）
HISTORY_SYNC_INTERVAL = float(os.environ.get("DASH_HISTORY_SYNC_INTERVAL", "5.0"))  # 增量同步间隔 (s)
HISTORY_GLOBAL = os.environ.get("DASH_HISTORY_GLOBAL", "0") == "1"  # 是否同步 /home/* 下所有用户的历史
HISTORY_MAX_ENTRIES = int(os.environ.get("DASH_HISTORY_MAX_ENTRIES", "200"))  # 首次导入的最大条数
