"""远程访问认证

策略：
- 来源为本机（127.0.0.1 / ::1）时默认免登录，本地使用体验不变；
- 来源为其他主机（局域网 / 公网）时必须账号密码登录，凭会话 Cookie 访问；
- 服务端未配置密码时，非本机访问一律拒绝（fail-closed），不会出现"开放但无口令"。

保护范围：/api/*（除 /api/auth/*）、/ws/*、/docs、/redoc、/openapi.json。
前端静态资源放行，让未登录用户能加载页面并看到登录页。
"""

import hashlib
import hmac
import json
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from config import (
    AUTH_LOCAL_BYPASS,
    AUTH_LOCK_SECONDS,
    AUTH_MAX_FAILS,
    AUTH_PASSWORD,
    AUTH_PASSWORD_HASH,
    AUTH_SESSION_TTL,
    AUTH_USER,
    TRUST_PROXY,
)

router = APIRouter()

COOKIE_NAME = "deckpit_session"
LOCAL_IPS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

# token -> 过期时间戳
_sessions: dict[str, float] = {}
# 来源标识 -> [连续失败次数, 解锁时间戳]
_failures: dict[str, list] = {}


# ── 口令 ──────────────────────────────────────────────────────────

def password_configured() -> bool:
    return bool(AUTH_PASSWORD_HASH or AUTH_PASSWORD)


def _expected_hash() -> str:
    if AUTH_PASSWORD_HASH:
        return AUTH_PASSWORD_HASH.strip().lower()
    return hashlib.sha256(AUTH_PASSWORD.encode("utf-8")).hexdigest()


def verify_password(username: str, password: str) -> bool:
    """常量时间比较，避免时序侧信道"""
    if not password_configured():
        return False
    if not hmac.compare_digest(username.encode("utf-8"), AUTH_USER.encode("utf-8")):
        return False
    given = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(given, _expected_hash())


# ── 会话 ──────────────────────────────────────────────────────────

def _gc_sessions() -> None:
    now = time.time()
    for token in [t for t, exp in _sessions.items() if exp <= now]:
        _sessions.pop(token, None)


def create_session() -> str:
    _gc_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + AUTH_SESSION_TTL
    return token


def valid_session(token: str | None) -> bool:
    if not token:
        return False
    exp = _sessions.get(token)
    if exp is None:
        return False
    if exp <= time.time():
        _sessions.pop(token, None)
        return False
    return True


def drop_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


# ── 来源判定 ──────────────────────────────────────────────────────

def client_ip(scope: dict) -> str:
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in (scope.get("headers") or [])}
    if TRUST_PROXY:
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else ""


def is_local(ip: str) -> bool:
    return ip in LOCAL_IPS


def is_local_scope(scope: dict) -> bool:
    return is_local(client_ip(scope))


# ── 登录失败限流 ──────────────────────────────────────────────────

def locked_seconds(ip: str) -> int:
    info = _failures.get(ip)
    if not info:
        return 0
    until = info[1]
    if until and until > time.time():
        return int(until - time.time())
    return 0


def record_failure(ip: str) -> None:
    info = _failures.get(ip) or [0, 0]
    info[0] += 1
    if info[0] >= AUTH_MAX_FAILS:
        info[1] = time.time() + AUTH_LOCK_SECONDS
    _failures[ip] = info


def clear_failures(ip: str) -> None:
    _failures.pop(ip, None)


# ── 路由 ──────────────────────────────────────────────────────────

class LoginPayload(BaseModel):
    username: str
    password: str


@router.get("/status")
async def auth_status(request: Request):
    """前端据此决定是否需要展示登录页"""
    ip = client_ip(request.scope)
    local = is_local(ip)
    authed = valid_session(request.cookies.get(COOKIE_NAME))
    return {
        "local": local,
        "auth_required": not (local and AUTH_LOCAL_BYPASS),
        "password_configured": password_configured(),
        "authenticated": authed,
        "user": AUTH_USER if authed else None,
        "locked_seconds": locked_seconds(ip),
    }


@router.post("/login")
async def login(payload: LoginPayload, request: Request, response: Response):
    ip = client_ip(request.scope)
    wait = locked_seconds(ip)
    if wait:
        raise HTTPException(429, f"失败次数过多，请 {wait} 秒后再试")

    if not password_configured():
        raise HTTPException(403, "服务端未配置 DASH_AUTH_PASSWORD，远程访问已禁用")

    if not verify_password(payload.username, payload.password):
        record_failure(ip)
        raise HTTPException(401, "用户名或密码错误")

    clear_failures(ip)
    token = create_session()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=AUTH_SESSION_TTL,
        path="/",
    )
    return {"ok": True, "user": AUTH_USER, "expires_in": AUTH_SESSION_TTL}


@router.post("/logout")
async def logout(request: Request, response: Response):
    drop_session(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


# ── 中间件 ────────────────────────────────────────────────────────

_PROTECTED_PREFIXES = ("/api/", "/ws/")
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")


def _needs_auth(path: str) -> bool:
    """仅保护数据面；静态资源放行以便前端能渲染登录页"""
    if path.startswith("/api/auth/"):
        return False
    if path.startswith(_PROTECTED_PREFIXES):
        return True
    if path in _DOCS_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
        return True
    return False


def _scope_path(scope: dict) -> str:
    path = scope.get("path") or ""
    if not path:
        raw = scope.get("raw_path") or b""
        path = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
    return path.split("?", 1)[0]


def _cookie_from_scope(scope: dict) -> str | None:
    for key, value in scope.get("headers") or []:
        if key.decode("latin-1").lower() != "cookie":
            continue
        raw = value.decode("latin-1")
        for part in raw.split(";"):
            name, _, val = part.partition("=")
            if name.strip() == COOKIE_NAME:
                return val.strip()
    return None


class AuthMiddleware:
    """纯 ASGI 中间件 —— 需同时拦截 HTTP 与 WebSocket 握手"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if not _needs_auth(_scope_path(scope)):
            await self.app(scope, receive, send)
            return

        ip = client_ip(scope)
        if is_local(ip) and AUTH_LOCAL_BYPASS:
            await self.app(scope, receive, send)
            return

        if valid_session(_cookie_from_scope(scope)):
            await self.app(scope, receive, send)
            return

        await self._deny(scope, receive, send)

    async def _deny(self, scope, receive, send):
        if scope["type"] == "websocket":
            # 先 accept 再以 1008 关闭，浏览器才能拿到确定关闭码（否则表现为 1006）
            try:
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": 1008, "reason": "unauthorized"})
                while True:
                    message = await receive()
                    if message["type"] in ("websocket.disconnect", "http.disconnect"):
                        return
            except Exception:
                pass
            return

        if not password_configured():
            status, detail = 403, "服务端未配置 DASH_AUTH_PASSWORD，远程访问已禁用"
        else:
            status, detail = 401, "需要登录"

        body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
