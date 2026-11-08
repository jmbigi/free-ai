from __future__ import annotations
from typing import Any, AsyncIterator
import httpx
from .base import BaseProvider, ModelInfo, ProviderError, parse_retry_after
from ..config import settings

class CloudflareProvider(BaseProvider):
    id = "cloudflare"
    label = "Cloudflare Workers AI (free daily neurons when configured)"

    def available(self) -> bool:
        return bool(settings.cloudflare_account_id and settings.cloudflare_api_token)

    @property
    def base_url(self):
        return f"https://api.cloudflare.com/client/v4/accounts/{settings.cloudflare_account_id}/ai/v1"

    async def list_models(self) -> list[ModelInfo]:
        defaults = [
            ("llama-3.3-70b-instruct-fp8-fast","@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
            ("llama-3.1-8b-instruct","@cf/meta/llama-3.1-8b-instruct"),
            ("qwen2.5-coder-32b-instruct","@cf/qwen/qwen2.5-coder-32b-instruct"),
            ("deepseek-r1-distill-qwen-32b","@cf/deepseek-ai/deepseek-r1-distill-qwen-32b"),
        ]
        return [ModelInfo(id=f"{self.id}/{m}", provider=self.id, owned_by="cloudflare", upstream_model=u,
                          capabilities=["chat"], note="Uses Cloudflare daily free neuron allocation; limits apply.")
                for m,u in defaults]

    def _headers(self):
        return {"Authorization": f"Bearer {settings.cloudflare_api_token}", "Content-Type": "application/json"}

    def _prepare(self, payload, upstream):
        body = {k:v for k,v in payload.items() if k not in {"model","provider","route"}}
        body["model"] = upstream
        return body

    async def chat(self, payload: dict[str, Any], model: ModelInfo) -> dict[str, Any]:
        body=self._prepare(payload, model.upstream_model or model.id); body["stream"]=False
        async with httpx.AsyncClient(timeout=180) as c:
            r=await c.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
        if r.status_code >= 400:
            raise ProviderError(
                f"Cloudflare error {r.status_code}: {r.text[:600]}",
                status=r.status_code, provider=self.id,
                retry_after=parse_retry_after(r.headers.get("retry-after")),
            )
        data=r.json(); data["provider"]=self.id; data["requested_model"]=model.id; return data

    async def stream_chat(self, payload: dict[str, Any], model: ModelInfo) -> AsyncIterator[bytes]:
        body=self._prepare(payload, model.upstream_model or model.id); body["stream"]=True
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
                        f"Cloudflare error {r.status_code}: {err[:600]}",
                        status=r.status_code, provider=self.id,
                        retry_after=parse_retry_after(r.headers.get("retry-after")),
                    )
                async for chunk in r.aiter_bytes():
                    if chunk: yield chunk
