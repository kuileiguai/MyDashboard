"""全局配置

配置优先级（高 → 低）：
    1. 真实环境变量（DASH_*）
    2. .env 文件
    3. 本文件里的默认值

.env 文件按以下顺序查找，命中第一个存在的文件即停止（多文件不合并）：
    1. $DASH_ENV_FILE 指定的路径
    2. 当前工作目录下的 .env
    3. backend/.env
    4. 项目根目录 .env
    5. ~/.config/deckpit.env

格式：每行 `KEY=VALUE`，支持 `#` 注释、`export` 前缀、引号包裹与 \\n 转义。
真实环境变量始终优先于 .env，所以临时覆盖仍可用 `DASH_PORT=9000 ./start.sh`。
"""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent


# ── .env 加载 ────────────────────────────────────────────────────

def _parse_dotenv(path: Path) -> dict[str, str]:
    """极简 .env 解析（无需额外依赖，兼容 python-dotenv 的常见写法）"""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            quote = val[0]
            val = val[1:-1]
            if quote == '"':
                val = val.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
        if key:
            values[key] = val
    return values


def _candidate_env_files() -> list[Path]:
    cands: list[Path] = []
    explicit = os.environ.get("DASH_ENV_FILE", "").strip()
    if explicit:
        cands.append(Path(explicit).expanduser())
    cands += [
        Path.cwd() / ".env",
        BACKEND_DIR / ".env",
        PROJECT_DIR / ".env",
        Path.home() / ".config" / "deckpit.env",
    ]
    return cands


def load_dotenv(override: bool = False) -> Path | None:
    """把 .env 内容写入 os.environ。override=False 时不覆盖已有环境变量。"""
    for path in _candidate_env_files():
        try:
            if not path.is_file():
                continue
            for key, val in _parse_dotenv(path).items():
                if override or key not in os.environ:
                    os.environ[key] = val
            return path
        except Exception:
            continue
    return None


ENV_FILE = load_dotenv()

if ENV_FILE:
    print(f"[config] 已加载配置文件: {ENV_FILE}", flush=True)


# ── 取值助手 ────────────────────────────────────────────────────

def _str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "").strip())
    except (ValueError, AttributeError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "").strip())
    except (ValueError, AttributeError):
        return default


def _bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _paths(key: str, default: str) -> list[Path]:
    raw = os.environ.get(key, default)
    return [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()]


# ── 服务器 ──────────────────────────────────────────────────────
HOST = _str("DASH_HOST", "127.0.0.1")
PORT = _int("DASH_PORT", 8787)

# ── 数据库 ──────────────────────────────────────────────────────
DB_DIR = Path(_str("DASH_DATA_DIR", str(PROJECT_DIR / "data"))).expanduser()
DB_PATH = DB_DIR / "dashboard.db"

# ── 采样 ────────────────────────────────────────────────────────
MONITOR_INTERVAL = _float("DASH_MONITOR_INTERVAL", 2.0)            # 活跃采样间隔 (s)
MONITOR_IDLE_INTERVAL = _float("DASH_MONITOR_IDLE_INTERVAL", 10.0)  # 无订阅时降频 (s)
MONITOR_HISTORY_POINTS = _int("DASH_MONITOR_HISTORY_POINTS", 150)   # 5 分钟 @ 2s

# ── PTY ─────────────────────────────────────────────────────────
PTY_SCROLLBACK_LINES = _int("DASH_PTY_SCROLLBACK_LINES", 5000)
PTY_MAX_SESSIONS = _int("DASH_PTY_MAX_SESSIONS", 20)

# ── 安全 ────────────────────────────────────────────────────────
ALLOWED_ROOTS = _paths("DASH_ALLOWED_ROOTS", "/")  # 默认全文件系统可访问，单用户本地环境无需限制
DISK_ALERT_THRESHOLD = _float("DASH_DISK_ALERT_THRESHOLD", 0.90)  # 90% 预警

# ── 日志 ────────────────────────────────────────────────────────
LOG_DIR = Path(_str("DASH_LOG_DIR", str(DB_DIR / "logs"))).expanduser()

# ── 远程访问认证（非本机来源需登录；本机来源默认免登录）────────────
AUTH_USER = _str("DASH_AUTH_USER", "admin")
AUTH_PASSWORD = _str("DASH_AUTH_PASSWORD", "")  # 明文，启动时转为摘要；空 = 非本机访问 fail-closed
AUTH_PASSWORD_HASH = _str("DASH_AUTH_PASSWORD_HASH", "")   # 直接给 sha256 摘要，优先级更高
AUTH_SESSION_TTL = _int("DASH_AUTH_SESSION_TTL", 12 * 3600)  # 会话有效期 (s)
AUTH_LOCAL_BYPASS = _bool("DASH_AUTH_LOCAL_BYPASS", True)   # 本机来源免登录
AUTH_MAX_FAILS = _int("DASH_AUTH_MAX_FAILS", 5)             # 同一来源连续失败上限
AUTH_LOCK_SECONDS = _int("DASH_AUTH_LOCK_SECONDS", 300)     # 触发后锁定时长 (s)

# 反向代理场景下用 X-Forwarded-For 判定来源；默认关闭，
# 开启后伪造该头即可冒充本机，仅在你确实挂了可信反代时才置 1。
TRUST_PROXY = _bool("DASH_TRUST_PROXY", False)

# ── shell 历史自动同步（全局指令收录）─────────────────────────────
HISTORY_SYNC_INTERVAL = _float("DASH_HISTORY_SYNC_INTERVAL", 5.0)  # 增量同步间隔 (s)
HISTORY_GLOBAL = _bool("DASH_HISTORY_GLOBAL", False)  # 是否同步 /home/* 下所有用户的历史
HISTORY_MAX_ENTRIES = _int("DASH_HISTORY_MAX_ENTRIES", 5000)  # 首次导入的最大条数（可在界面「收录设置」改）

# ── AI 对话 ──────────────────────────────────────────────────────
AI_ENABLED = _bool("DASH_AI_ENABLED", True)
AI_PROVIDER = _str("DASH_AI_PROVIDER", "openai-compatible")
AI_BASE_URL = _str("DASH_AI_BASE_URL", "http://127.0.0.1:11434/v1")
AI_MODEL = _str("DASH_AI_MODEL", "")
AI_API_KEY = _str("DASH_AI_API_KEY", "")
AI_TIMEOUT = _float("DASH_AI_TIMEOUT", 120.0)          # 单次模型请求读超时 (s)
AI_CONNECT_TIMEOUT = _float("DASH_AI_CONNECT_TIMEOUT", 5.0)
AI_MAX_TOKENS = _int("DASH_AI_MAX_TOKENS", 4096)
AI_TEMPERATURE = _float("DASH_AI_TEMPERATURE", 0.3)
AI_CONTEXT_BUDGET = _int("DASH_AI_CONTEXT_BUDGET", 32000)  # 估算 token 预算
AI_ALLOW_CLOUD = _bool("DASH_AI_ALLOW_CLOUD", False)       # 是否允许公网模型地址
AI_ACTION_MODE = _str("DASH_AI_ACTION_MODE", "confirm_all")  # confirm_all/confirm_stop/auto_start
AI_MAX_TOOL_ROUNDS = _int("DASH_AI_MAX_TOOL_ROUNDS", 3)
AI_MAX_TOOL_RESULT_BYTES = _int("DASH_AI_MAX_TOOL_RESULT_BYTES", 65536)
AI_ACTION_TIMEOUT = _float("DASH_AI_ACTION_TIMEOUT", 60.0)
AI_CATALOG_CACHE_TTL = _float("DASH_AI_CATALOG_CACHE_TTL", 5.0)
AI_ENV_CACHE_TTL = _float("DASH_AI_ENV_CACHE_TTL", 60.0)
