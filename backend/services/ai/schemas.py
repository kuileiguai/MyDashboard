"""AI 路由的请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str = Field(min_length=1, max_length=20000)
    context: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None


class ConversationCreate(BaseModel):
    title: str = ""
    project_id: int | None = None


class ConversationPatch(BaseModel):
    title: str | None = None
    archived: bool | None = None


class ProviderIn(BaseModel):
    name: str = "default"
    kind: str = "openai-compatible"
    base_url: str = ""
    model: str = ""
    api_key: str | None = None
    enabled: bool = True
    is_default: bool = True
    timeout: float | None = None
    supports_tools: bool = True


class ProviderTestIn(BaseModel):
    use_saved: bool = True
