"""敏感信息脱敏。

原则：
- 只做“展示/送模型前”的兜底，不替代字段级白名单；
- SSH 密码、API Key、私钥、常见 token 赋值都要打码；
- 宁可多打码，也不要把密钥送进模型上下文。
"""

from __future__ import annotations

import re
from typing import Any

# 字段名精确匹配（不做 key 的模糊匹配，避免把 key_path 这类路径误伤）
_SENSITIVE_KEYS = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "authorization", "private_key", "credential", "credentials",
    "access_key", "secret_key", "auth_token", "session_token",
}

# 常见的 KEY=VALUE / KEY: VALUE 形式（只打码值，保留键名，便于理解）
_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|apikey|"
    r"authorization|access[_-]?key|secret[_-]?key|auth[_-]?token)\b"
    r"(\s*[:=]\s*)(['\"]?)([^\s'\"\\]+)(\3)"
)

_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.S,
)
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_AK_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def redact_text(value: str) -> str:
    """对一段文本做常见密钥脱敏。"""
    if not value:
        return value
    out = _PRIVATE_KEY_RE.sub("[PRIVATE KEY REDACTED]", value)
    out = _BEARER_RE.sub("Bearer [REDACTED]", out)
    out = _SK_RE.sub("sk-[REDACTED]", out)
    out = _AK_RE.sub("AKIA[REDACTED]", out)
    out = _ASSIGN_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}***{m.group(5)}", out)
    return out


def redact_obj(value: Any) -> Any:
    """递归脱敏 dict/list；敏感字段名直接替换为 ***。"""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = "***" if v not in (None, "") else v
            else:
                out[k] = redact_obj(v)
        return out
    if isinstance(value, list):
        return [redact_obj(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_obj(v) for v in value)
    if isinstance(value, str):
        return redact_text(value)
    return value
