"""Provider-neutral contracts for portable text chat."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol


ChatRole = Literal["user", "assistant"]
ToolChoice = Literal["auto", "generate_image"]


@dataclass(frozen=True)
class TextModel:
    id: str
    name: str
    provider: str
    description: str = ""


@dataclass(frozen=True)
class ChatTurn:
    role: ChatRole
    content: str


@dataclass(frozen=True)
class ProviderChatRequest:
    model: str
    messages: tuple[ChatTurn, ...]
    tool_choice: ToolChoice = "auto"


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


ProviderEvent = TextDelta | ToolCall | Usage


class ProviderError(RuntimeError):
    def __init__(self, code: str, public_message: str, *, status_code: int = 502) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.status_code = status_code


class TextProvider(Protocol):
    provider_id: str

    def models(self) -> tuple[TextModel, ...]:
        ...

    async def check(self, api_key: str) -> tuple[TextModel, ...]:
        ...

    def stream(self, api_key: str, request: ProviderChatRequest) -> AsyncIterator[ProviderEvent]:
        ...
