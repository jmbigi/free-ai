from __future__ import annotations
from typing import Any, AsyncIterator
import httpx
from .base import BaseProvider, ModelInfo, ProviderError, parse_retry_after
from ..config import settings

class GeminiProvider(BaseProvider):
    id = "gemini"
    label = "Google Gemini (free tier when key configured)"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai"

    def available(self) -> bool:
        return bool(settings.gemini_api_key)

    async def list_models(self) -> list[ModelInfo]:
        defaults = [
            ("gemini-2.5-flash", "gemini-2.5-flash", ["chat","vision"]),
            ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite", ["chat","vision"]),
            ("gemini-2.0-flash", "gemini-2.0-flash", ["chat","vision"]),
        ]
        return [ModelInfo(id=f"{self.id}/{m}", provider=self.id, owned_by="google", upstream_model=u,
                          capabilities=caps, note="Gemini free tier limits apply; check AI Studio dashboard.")
                for m,u,caps in defaults]

    def _headers(self):
        return {"Authorization": f"Bearer {settings.gemini_api_key}", "Content-Type": "application/json"}

    def _prepare(self, payload: dict[str, Any], upstream: str):
        body = {k:v for k,v in payload.items() if k not in {"model","provider","route"}}
        body["model"] = upstream
        return body

    async def chat(self, payload: dict[str, Any], model: ModelInfo) -> dict[str, Any]:
        body = self._prepare(payload, model.upstream_model or model.id); body["stream"]=False
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
        if r.status_code >= 400:
            raise ProviderError(
                f"Gemini error {r.status_code}: {r.text[:600]}",
                status=r.status_code, provider=self.id,
                retry_after=parse_retry_after(r.headers.get("retry-after")),
            )
        data=r.json(); data["provider"]=self.id; data["requested_model"]=model.id; return data

    async def stream_chat(self, payload: dict[str, Any], model: ModelInfo) -> AsyncIterator[bytes]:
        body = self._prepare(payload, model.upstream_model or model.id); body["stream"]=True
        timeout = httpx.Timeout(
            connect=10.0,
            read=float(getattr(settings, 'request_timeout', 120) or 120),
            write=30.0,
            pool=10.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", f"{self.base_url}/chat/completions", json=body, headers=self._headers()) as r:
                if r.status_code >= 400:
                    err=(await r.aread()).decode(errors="ignore")
                    raise ProviderError(
                        f"Gemini error {r.status_code}: {err[:600]}",
                        status=r.status_code, provider=self.id,
                        retry_after=parse_retry_after(r.headers.get("retry-after")),
                    )
                async for chunk in r.aiter_bytes():
                    if chunk: yield chunk
