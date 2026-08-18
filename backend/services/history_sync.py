"""shell 历史自动同步服务

后台任务：增量读取 ~/.bash_history / ~/.zsh_history（可选全局 /home/*），
把新出现的命令自动收录进 terminal_history（source='shell'），实现"机器全局指令自动收录"。

- 首次遇到某历史文件：导入其最近 HISTORY_MAX_ENTRIES 条命令（倒序去重）。
- 之后：只读文件新增部分，去重后增量入库。
- 每个文件的读取偏移量持久化在 settings 表（key: history_sync_offset:<abs_path>）。
"""

import asyncio
import logging
import os
import re
from pathlib import Path

from config import HISTORY_GLOBAL, HISTORY_MAX_ENTRIES, HISTORY_SYNC_INTERVAL
from database import get_db

logger = logging.getLogger("history_sync")

_OFFSET_PREFIX = "history_sync_offset:"

# zsh 扩展历史格式: ": 1234567890:0;command"
_ZSH_TS_RE = re.compile(r"^: \d+:\d+;(.*)$")


def _history_files() -> list[Path]:
    """返回要同步的历史文件列表"""
    homes = {Path.home()}
    if HISTORY_GLOBAL:
        base = Path("/home")
        if base.is_dir():
            try:
                for p in base.iterdir():
                    if p.is_dir():
                        homes.add(p)
            except OSError:
                pass

    files: list[Path] = []
    for h in homes:
        for name in (".bash_history", ".zsh_history"):
            f = h / name
            if f.is_file() and os.access(f, os.R_OK):
                files.append(f)
    return files


def _parse_command(raw: str) -> str | None:
    """把一行历史记录解析为命令文本，非法/超长返回 None"""
    m = _ZSH_TS_RE.match(raw)
    if m:
        raw = m.group(1)
    elif raw.startswith(": ") and ";" in raw:
        # 兼容旧解析逻辑
        raw = raw.split(";", 1)[1]
    cmd = raw.strip()
    if not cmd or len(cmd) > 200:
        return None
    return cmd


def _read_lines_from(path: Path, offset: int) -> list[str]:
    """从字节偏移 offset 读取到文件末尾，返回非空行列表"""
    with open(path, "r", errors="replace") as f:
        f.seek(offset)
        data = f.read()
    return [l.rstrip("\n\r") for l in data.split("\n")]


async def _load_offsets() -> dict[str, int]:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT key, value FROM settings WHERE key LIKE ?", (_OFFSET_PREFIX + "%",)
        )
    out: dict[str, int] = {}
    for r in rows:
        try:
            out[r["key"][len(_OFFSET_PREFIX):]] = int(r["value"])
        except (ValueError, KeyError, TypeError):
            pass
    return out


async def _sync_once(offsets: dict[str, int]) -> dict[str, int]:
    """执行一轮同步，返回更新后的偏移映射"""
    new_offsets = dict(offsets)
    added = 0

    async with get_db() as db:
        existing_rows = await db.execute_fetchall("SELECT command FROM terminal_history")
        existing = {r["command"] for r in existing_rows}

        for f in _history_files():
            key = str(f)
            try:
                size = f.stat().st_size
            except OSError:
                continue

            first_time = key not in offsets
            offset = 0 if first_time else offsets.get(key, 0)
            if offset > size:
                offset = 0  # 文件被截断/重写，从头读（去重会挡住已存在的）

            lines = _read_lines_from(f, offset)
            new_offsets[key] = size

            cmds: list[str] = []
            for raw in lines:
                c = _parse_command(raw)
                if c and c not in existing:
                    cmds.append(c)
                    existing.add(c)

            if first_time:
                # 首次只导入文件末尾最近的 N 条，避免历史全量涌入
                cmds = cmds[-HISTORY_MAX_ENTRIES:]

            for c in cmds:
                await db.execute(
                    "INSERT INTO terminal_history (session_id, command, cwd, source) VALUES (?,?,?,?)",
                    ("", c, "", "shell"),
                )
                added += 1

        for key, off in new_offsets.items():
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (_OFFSET_PREFIX + key, str(off)),
            )
        await db.commit()

    if added:
        logger.info("history_sync 收录 %d 条 shell 历史", added)
    return new_offsets


async def history_sync_loop():
    """后台 shell 历史增量同步任务（在 lifespan 中启动）"""
    offsets = await _load_offsets()
    while True:
        try:
            offsets = await _sync_once(offsets)
        except Exception as e:
            logger.warning("history_sync 同步失败: %s", e)
        await asyncio.sleep(HISTORY_SYNC_INTERVAL)
