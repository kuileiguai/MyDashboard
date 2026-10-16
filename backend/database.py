"""SQLite 连接与建表"""

import aiosqlite
from contextlib import asynccontextmanager
from config import DB_PATH, DB_DIR, LOG_DIR

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT '',
    service TEXT NOT NULL DEFAULT '',
    scenario TEXT NOT NULL DEFAULT '',
    command TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '[]',
    examples_json TEXT NOT NULL DEFAULT '[]',
    is_favorite INTEGER NOT NULL DEFAULT 0,
    use_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ssh_hosts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL DEFAULT '',
    key_path TEXT NOT NULL DEFAULT '',
    jump_host TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS terminal_meta (
    session_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    cwd TEXT NOT NULL DEFAULT '',
    group_name TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS usage_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    ref_id INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recent_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS terminal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    command TEXT NOT NULL,
    cwd TEXT NOT NULL DEFAULT '',
    exit_code INTEGER NOT NULL DEFAULT 0,
    is_favorite INTEGER NOT NULL DEFAULT 0,
    run_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS port_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS port_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    port INTEGER NOT NULL DEFAULT 0,
    protocol TEXT NOT NULL DEFAULT '',
    process_name TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    snapshot_id INTEGER NOT NULL DEFAULT 0,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL DEFAULT '',
    terminal_group TEXT NOT NULL DEFAULT '',
    env_name TEXT NOT NULL DEFAULT '',
    command_group TEXT NOT NULL DEFAULT '',
    log_paths TEXT NOT NULL DEFAULT '[]',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS remote_bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ssh_host_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ssh_host_id) REFERENCES ssh_hosts(id)
);

CREATE TABLE IF NOT EXISTS file_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    extension TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS favorite_terminals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS service_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    remark TEXT,
    workdir TEXT,
    commands TEXT NOT NULL DEFAULT '[]',
    ports TEXT NOT NULL DEFAULT '[]',
    auto_start INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS taxonomy (
    type TEXT NOT NULL,
    value TEXT NOT NULL,
    sort INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (type, value)
);
"""


async def init_db():
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.executescript(SCHEMA)
        # 迁移：为已有表补充新列
        try:
            await db.execute("ALTER TABLE terminal_history ADD COLUMN source TEXT NOT NULL DEFAULT 'terminal'")
        except Exception:
            pass  # 列已存在
        try:
            await db.execute("ALTER TABLE terminal_history ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass  # 列已存在
        # 真实执行次数：同命令只留一行，重复执行时累加，供 Top 榜统计
        try:
            await db.execute("ALTER TABLE terminal_history ADD COLUMN run_count INTEGER NOT NULL DEFAULT 1")
        except Exception:
            pass  # 列已存在
        # 二级分类：所属服务 / 所属场景
        try:
            await db.execute("ALTER TABLE commands ADD COLUMN service TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # 列已存在
        try:
            await db.execute("ALTER TABLE commands ADD COLUMN scenario TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # 列已存在
        # SSH 主机密码（加密后存放，详见 services/ssh_secret.py）
        try:
            await db.execute("ALTER TABLE ssh_hosts ADD COLUMN password TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # 列已存在
        # 字典表首次创建时把 commands 表里已有值回填（IGNORE 不会覆盖已有）
        for t in ("category", "service", "scenario"):
            try:
                await db.execute(
                    f"INSERT OR IGNORE INTO taxonomy (type, value) "
                    f"SELECT DISTINCT '{t}', {t} FROM commands "
                    f"WHERE {t} != '' AND {t} IS NOT NULL")
            except Exception:
                pass
        await db.commit()


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()
