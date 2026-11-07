from __future__ import annotations
from typing import Any, AsyncIterator
import httpx
from .base import BaseProvider, ModelInfo, ProviderError

BASE = "https://text.pollinations.ai"

class PollinationsProvider(BaseProvider):
    id = "pollinations"
    label = "Pollinations (anonymous free tier)"

    def available(self) -> bool:
        return True

    async def list_models(self) -> list[ModelInfo]:
        models = [
            ModelInfo(id="pollinations/openai-fast", provider=self.id, owned_by="pollinations",
                      upstream_model="openai-fast", capabilities=["chat", "tools", "reasoning"],
                      note="Anonymous, rate-limited per IP; no upstream key required."),
            ModelInfo(id="pollinations/openai", provider=self.id, owned_by="pollinations",
                      upstream_model="openai", capabilities=["chat", "tools", "reasoning"],
                      note="Alias; anonymous free tier."),
        ]
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{BASE}/models")
                if r.status_code == 200:
                    for m in r.json():
                        mid = m.get("name")
                        if not mid:
                            continue
                        aliases = m.get("aliases") or []
                        for name in [mid] + aliases:
                            pid = f"pollinations/{name}"
                            if not any(x.id == pid for x in models):
                                models.append(ModelInfo(
                                    id=pid, provider=self.id, owned_by="pollinations",
                                    upstream_model=mid,
                                    capabilities=(["chat","tools"] if m.get("tools") else ["chat"]) + (["reasoning"] if m.get("reasoning") else []),
                                    note="Anonymous, rate-limited per IP."))
        except Exception:
            pass
        return models

    def _prepare(self, payload: dict[str, Any], upstream: str) -> dict[str, Any]:
        drop = {"model","provider","route","api_key","apikey","key","prompt","input","access_token","token"}
        body = {k: v for k, v in payload.items() if k not in drop}
        if 'messages' not in body and 'prompt' in payload:
            p = payload['prompt']; body['messages']=[{'role':'user','content': "\n".join(p) if isinstance(p,list) else str(p)}]
        body["model"] = upstream
        body.setdefault("stream", False)
        if 'max_tokens' in body and 'max_completion_tokens' in body:
            body.pop('max_completion_tokens', None)
        return body

    async def chat(self, payload: dict[str, Any], model: ModelInfo) -> dict[str, Any]:
        body = self._prepare(payload, model.upstream_model or "openai-fast")
        body["stream"] = False
        timeout = httpx.Timeout(25.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{BASE}/openai", json=body)
        if r.status_code >= 400:
            raise ProviderError(f"Pollinations error {r.status_code}: {r.text[:350]}", status=r.status_code, provider=self.id)
        data = r.json()
        if isinstance(data, dict):
            data["provider"] = self.id
            data["requested_model"] = model.id
            data.setdefault("gateway", {})
        return data

    async def stream_chat(self, payload: dict[str, Any], model: ModelInfo) -> AsyncIterator[bytes]:
        body = self._prepare(payload, model.upstream_model or "openai-fast")
        body["stream"] = True
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("POST", f"{BASE}/openai", json=body) as r:
                if r.status_code >= 400:
                    err = (await r.aread()).decode(errors="ignore")
                    raise ProviderError(f"Pollinations error {r.status_code}: {err[:350]}", status=r.status_code, provider=self.id)
                async for chunk in r.aiter_bytes():
                    if chunk:
                        yield chunk
