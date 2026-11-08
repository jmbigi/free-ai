from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
    def __init__(self, message: str, status: int = 502, provider: str = "", retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.provider = provider
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> float | None:
    """Parse RFC 9110 Retry-After (delta-seconds or HTTP-date) into seconds."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None

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
