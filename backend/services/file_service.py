"""M2 文件操作服务"""

import os
import shutil
from pathlib import Path
from config import ALLOWED_ROOTS


def safe_resolve(user_path: str) -> Path:
    p = Path(user_path).expanduser().resolve()
    for root in ALLOWED_ROOTS:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    raise PermissionError(f"Path {p} outside allowed roots {ALLOWED_ROOTS}")


def get_file_info(path: str) -> dict:
    p = safe_resolve(path)
    st = p.stat()
    return {
        "path": str(p),
        "name": p.name,
        "is_dir": p.is_dir(),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "ctime": st.st_ctime,
        "mode": oct(st.st_mode),
    }
