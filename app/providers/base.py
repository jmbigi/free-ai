from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

@dataclass
class ModelInfo:
    id: str
    provider: str
    owned_by: str
    context_window: int | None = None
    capabilities: list[str] = field(default_factory=list)
    free: bool = True
    upstream_model: str | None = None
    note: str = ""

class ProviderError(Exception):
    def __init__(self, message: str, status: int = 502, provider: str = ""):
        super().__init__(message)
        self.status = status
        self.provider = provider

class BaseProvider:
    id: str = "base"
    label: str = "Base"

    def available(self) -> bool:
        return False

    async def list_models(self) -> list[ModelInfo]:
        return []

    async def chat(self, payload: dict[str, Any], model: ModelInfo) -> dict[str, Any]:
        raise ProviderError("Not implemented", provider=self.id)

    async def stream_chat(self, payload: dict[str, Any], model: ModelInfo) -> AsyncIterator[bytes]:
        raise ProviderError("Streaming not implemented", provider=self.id)
        if False:
            yield b""
