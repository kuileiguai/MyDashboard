"""终端历史的时间戳生成：毫秒精度 + 进程内严格单调递增。

SQLite 的 CURRENT_TIMESTAMP / strftime('%f') 只有毫秒精度，且同一毫秒内写入的多条
命令（本地写很快、批内同步、批量导入都很常见）created_at 完全相同；而历史列表按
created_at DESC 排序，并列时只能靠 id 兜底，于是"刚执行过的命令排到最前面"会失效。

这里统一生成 'YYYY-MM-DD HH:MM:SS.mmm'（UTC，与 CURRENT_TIMESTAMP 同一口径，
新老数据可直接比较排序），并保证同一毫秒内后写的时间戳更大。
"""

import threading
import time

_lock = threading.Lock()
_last_ms = 0


def next_ts() -> str:
    """取下一个严格递增的时间戳字符串（UTC，毫秒精度）"""
    global _last_ms
    with _lock:
        ms = int(time.time() * 1000)
        if ms <= _last_ms:
            ms = _last_ms + 1
        _last_ms = ms
    secs, msec = divmod(ms, 1000)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(secs)) + ".%03d" % msec
