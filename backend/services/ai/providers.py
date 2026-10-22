"""模型 Provider：OpenAI-compatible + 本地 Mock。

只用 httpx，不引入各家 SDK；换模型/换厂商只改 base_url/model。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

import config
from database import get_db
from services.ssh_secret import decrypt_secret


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class ProviderConfig:
    name: str = "default"
    kind: str = "openai-compatible"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    timeout: float = 120.0
    connect_timeout: float = 5.0
    max_tokens: int = 4096
    temperature: float = 0.3
    supports_tools: bool = True


@dataclass
class _ToolSlot:
    id: str = ""
    name: str = ""
    arguments: str = ""


def _is_private_url(base_url: str) -> bool:
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}:
        return True
    if host.endswith((".local", ".internal", ".lan")):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        # 单标签主机名（如 gpu-server）按内网处理；含点的域名按公网处理
        return "." not in host


# 供路由层做保存前校验
is_private_url = _is_private_url


def _endpoint(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


class BaseProvider:
    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg

    async def stream_chat(self, messages: list[dict], tools: list[dict] | None = None,
                          max_tokens: int | None = None) -> AsyncIterator[dict]:
        raise NotImplementedError

    async def ping(self) -> dict:
        raise NotImplementedError


class OpenAICompatibleProvider(BaseProvider):
    """标准 OpenAI /v1/chat/completions 协议。"""

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        return headers

    def _payload(self, messages: list[dict], tools: list[dict] | None,
                 stream: bool, max_tokens: int | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": stream,
            "temperature": self.cfg.temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.cfg.timeout, connect=self.cfg.connect_timeout),
            follow_redirects=True,
            # 开发机常带 HTTP_PROXY/NO_PROXY，NO_PROXY 里的 [::1] 会让 httpx 解析失败；
            # 本地模型直连，不读代理环境变量。
            trust_env=False,
        )

    async def stream_chat(self, messages: list[dict], tools: list[dict] | None = None,
                          max_tokens: int | None = None) -> AsyncIterator[dict]:
        if not self.cfg.base_url or not self.cfg.model:
            raise ProviderError("not_configured", "未配置模型地址或模型名", 400)

        payload = self._payload(messages, tools, True, max_tokens)
        slots: dict[int, _ToolSlot] = {}
        usage: dict = {}

        try:
            async with self._client() as client:
                async with client.stream("POST", _endpoint(self.cfg.base_url),
                                         json=payload, headers=self._headers()) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", errors="replace")
                        raise ProviderError(
                            "model_error",
                            f"模型返回 HTTP {resp.status_code}: {body[:500]}",
                            502,
                        )

                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        if obj.get("usage"):
                            usage = obj["usage"]

                        for choice in obj.get("choices") or []:
                            delta = choice.get("delta") or {}
                            content = delta.get("content")
                            if content:
                                yield {"type": "token", "delta": content}

                            for tc in delta.get("tool_calls") or []:
                                idx = int(tc.get("index", 0))
                                slot = slots.setdefault(idx, _ToolSlot())
                                if tc.get("id"):
                                    slot.id = tc["id"]
                                fn = tc.get("function") or {}
                                if fn.get("name") and not slot.name:
                                    slot.name = fn["name"]
                                if fn.get("arguments"):
                                    slot.arguments += fn["arguments"]

        except ProviderError:
            raise
        except httpx.ConnectError as e:
            raise ProviderError("model_unreachable", f"无法连接模型服务: {e}", 502)
        except httpx.TimeoutException:
            raise ProviderError("model_timeout", "模型请求超时", 504)
        except httpx.HTTPError as e:
            raise ProviderError("model_error", f"模型请求失败: {e}", 502)

        tool_calls = []
        for idx in sorted(slots.keys()):
            slot = slots[idx]
            if not slot.name:
                continue
            tool_calls.append({
                "id": slot.id or f"call_{idx}",
                "type": "function",
                "function": {"name": slot.name, "arguments": slot.arguments or "{}"},
            })

        yield {"type": "end", "tool_calls": tool_calls, "usage": usage}

    async def ping(self) -> dict:
        if not self.cfg.base_url or not self.cfg.model:
            raise ProviderError("not_configured", "未配置模型地址或模型名", 400)
        started = time.time()
        try:
            # 健康检查用短超时，避免悬浮窗/网页被不可达模型卡住
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10, connect=5),
                follow_redirects=True,
                trust_env=False,
            ) as client:
                resp = await client.post(
                    _endpoint(self.cfg.base_url),
                    json=self._payload(
                        [{"role": "user", "content": "ping"}], None, False, max_tokens=1),
                    headers=self._headers(),
                )
        except httpx.ConnectError as e:
            raise ProviderError("model_unreachable", f"无法连接模型服务: {e}", 502)
        except httpx.TimeoutException:
            raise ProviderError("model_timeout", "模型请求超时", 504)
        except httpx.HTTPError as e:
            raise ProviderError("model_error", f"模型请求失败: {e}", 502)

        if resp.status_code >= 400:
            body = resp.text[:500]
            raise ProviderError("model_error", f"模型返回 HTTP {resp.status_code}: {body}", 502)
        return {
            "ok": True,
            "model": self.cfg.model,
            "base_url": self.cfg.base_url,
            "latency_ms": int((time.time() - started) * 1000),
        }


class MockProvider(BaseProvider):
    """无模型时用于开发/测试；不会真正执行任何动作。"""

    async def stream_chat(self, messages: list[dict], tools: list[dict] | None = None,
                          max_tokens: int | None = None) -> AsyncIterator[dict]:
        last = messages[-1] if messages else {}
        last_role = last.get("role")
        text = str(last.get("content") or "")

        if last_role == "tool":
            answer = "（Mock）我已读取到系统配置。接入真实模型后，这里会基于配置给出准确回答。"
            for ch in answer:
                yield {"type": "token", "delta": ch}
                await asyncio.sleep(0)
            yield {"type": "end", "tool_calls": [], "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
            return

        if any(k in text for k in ("服务", "配置", "端口")):
            yield {
                "type": "end",
                "tool_calls": [{
                    "id": "call_mock_1",
                    "type": "function",
                    "function": {"name": "catalog_overview", "arguments": "{}"},
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }
            return

        answer = (
            "（Mock 模式）这是一个本地开发用的占位回答。"
            "配置 DASH_AI_BASE_URL / DASH_AI_MODEL 或页面里的模型设置后，即可接入真实模型。"
        )
        for ch in answer:
            yield {"type": "token", "delta": ch}
            await asyncio.sleep(0)
        yield {"type": "end", "tool_calls": [], "usage": {"prompt_tokens": 0, "completion_tokens": 0}}

    async def ping(self) -> dict:
        return {"ok": True, "model": "mock", "base_url": "", "latency_ms": 0}


# ── Provider 加载 ─────────────────────────────────────────────────

async def _load_provider_row() -> dict | None:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM ai_providers WHERE enabled = 1 "
            "ORDER BY is_default DESC, id ASC LIMIT 1")
    return dict(rows[0]) if rows else None


async def get_active_provider(model_override: str | None = None) -> BaseProvider:
    row = await _load_provider_row()

    kind = (row.get("kind") if row else config.AI_PROVIDER) or "openai-compatible"
    base_url = ((row.get("base_url") if row else "") or config.AI_BASE_URL or "").strip()
    model = (model_override or (row.get("model") if row else "") or config.AI_MODEL or "").strip()
    api_key = ""
    supports_tools = True
    timeout = config.AI_TIMEOUT

    if row:
        api_key = decrypt_secret(row.get("api_key_enc") or "")
        try:
            extra = json.loads(row.get("extra_json") or "{}")
        except Exception:
            extra = {}
        supports_tools = bool(extra.get("supports_tools", True))
        try:
            timeout = float(extra.get("timeout") or timeout)
        except (TypeError, ValueError):
            timeout = config.AI_TIMEOUT
    else:
        api_key = config.AI_API_KEY

    if not api_key:
        api_key = config.AI_API_KEY

    if kind == "mock":
        return MockProvider(ProviderConfig(kind="mock", model="mock"))

    if not base_url or not model:
        raise ProviderError("not_configured", "尚未配置模型地址或模型名", 400)

    if not config.AI_ALLOW_CLOUD and not _is_private_url(base_url):
        raise ProviderError(
            "cloud_not_allowed",
            "当前只允许本机/内网模型地址；如需公网模型请设置 DASH_AI_ALLOW_CLOUD=1",
            400,
        )

    cfg = ProviderConfig(
        name=(row.get("name") if row else "default") or "default",
        kind=kind,
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        connect_timeout=config.AI_CONNECT_TIMEOUT,
        max_tokens=config.AI_MAX_TOKENS,
        temperature=config.AI_TEMPERATURE,
        supports_tools=supports_tools,
    )
    return OpenAICompatibleProvider(cfg)


# ── 健康检查缓存 ──────────────────────────────────────────────────

_health_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def invalidate_health() -> None:
    _health_cache["ts"] = 0.0
    _health_cache["data"] = None


async def health(force: bool = False) -> dict:
    now = time.time()
    if not force and _health_cache["data"] is not None and (now - _health_cache["ts"]) < 30:
        return _health_cache["data"]

    data: dict
    if not config.AI_ENABLED:
        data = {"enabled": False, "ok": False, "code": "disabled",
                "message": "AI 功能已关闭（DASH_AI_ENABLED=0）"}
    else:
        try:
            provider = await get_active_provider()
            ping = await provider.ping()
            data = {"enabled": True, "ok": True, **ping}
        except ProviderError as e:
            data = {"enabled": True, "ok": False, "code": e.code, "message": e.message}
        except Exception as e:
            data = {"enabled": True, "ok": False, "code": "unknown", "message": str(e)}

    _health_cache["ts"] = now
    _health_cache["data"] = data
    return data
