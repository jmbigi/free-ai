from __future__ import annotations
from typing import Any, AsyncIterator
import httpx
from .base import BaseProvider, ModelInfo, ProviderError, parse_retry_after
from ..config import settings
from ..normalize import normalize_chat_response

_ALLOWED = {
    'messages','model','frequency_penalty','logit_bias','logprobs','top_logprobs','max_tokens','max_completion_tokens',
    'n','presence_penalty','response_format','seed','stop','stream','stream_options','temperature','top_p','tools','tool_choice',
    'parallel_tool_calls','user','metadata','reasoning_effort','extra_body',
    # thinking / reasoning passthrough for clients like KimiCode
    'reasoning','reasoning_content','thinking','thought','reasoning_budget','reasoning_tokens',
}
_DROP = {'provider','route','api_key','apikey','key','prompt','input','access_token','token'}

# Tool-related fields that MUST always pass through even if not in _ALLOWED
_TOOL_FIELDS = {
    'tools', 'tool_choice', 'parallel_tool_calls', 'function_call',
    'tool_prompt', 'tool_output', 'tool_return', 'turn_id',
}


class OpenAICompatProvider(BaseProvider):
    base_url: str = ""
    api_key: str = ""
    extra_headers: dict[str, str] = {}
    model_prefix: str = ""
    default_models: list[tuple[str, str, list[str], str]] = []  # (id, upstream, caps, note)

    def available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        h.update(self.extra_headers)
        return h

    async def list_models(self) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        for mid, upstream, caps, note in self.default_models:
            out.append(ModelInfo(id=f"{self.id}/{mid}", provider=self.id, owned_by=self.id,
                                 upstream_model=upstream, capabilities=caps, note=note))
        if not self.base_url or not self.available():
            return out
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{self.base_url.rstrip('/')}/models", headers=self._headers())
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("data") if isinstance(data, dict) else data
                    for m in items or []:
                        raw = (m.get("id") or m.get("name") or "").strip() if isinstance(m, dict) else str(m)
                        if not raw or any(x.upstream_model == raw for x in out):
                            continue
                        out.append(ModelInfo(id=f"{self.id}/{raw}", provider=self.id, owned_by=self.id,
                                             upstream_model=raw, capabilities=["chat"], note="Discovered from provider /models."))
        except Exception as e:
            import logging
            logging.getLogger("free-ai.providers").warning("list_models failed for %s: %s", self.id, e)
        return out

    def _prepare(self, payload: dict[str, Any], upstream: str) -> dict[str, Any]:
        body: dict[str, Any] = {}
        for k, v in payload.items():
            if k in _DROP:
                continue
            if k in _ALLOWED or k.startswith('x_'):
                body[k] = v
        # Ensure ALL tool fields always pass through (client may send fields not in _ALLOWED)
        for tf in _TOOL_FIELDS:
            if tf in payload:
                body[tf] = payload[tf]
        # ensure chat format for chat/completions
        if 'messages' not in body and 'prompt' in payload:
            p = payload['prompt']
            body['messages'] = [{'role':'user','content': "\n".join(p) if isinstance(p,list) else str(p)}]
        body["model"] = upstream
        # avoid both prompt/messages; avoid max_completion_tokens conflict on older backends by keeping max_tokens
        body.pop('prompt', None)
        body.pop('input', None)
        if 'max_tokens' in body and 'max_completion_tokens' in body:
            body.pop('max_completion_tokens', None)
        return body

    async def chat(self, payload: dict[str, Any], model: ModelInfo) -> dict[str, Any]:
        body = self._prepare(payload, model.upstream_model or model.id)
        body["stream"] = False
        timeout = httpx.Timeout(float(getattr(settings, 'request_timeout', 45) or 45), connect=8.0)
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{self.base_url.rstrip('/')}/chat/completions", json=body, headers=self._headers())
        if r.status_code >= 400:
            raise ProviderError(
                f"{self.label} error {r.status_code}: {r.text[:350]}",
                status=r.status_code, provider=self.id,
                retry_after=parse_retry_after(r.headers.get("retry-after")),
            )
        data = r.json()
        if isinstance(data, dict):
            data["provider"] = self.id
            data["requested_model"] = model.id
        return normalize_chat_response(data)

    async def stream_chat(self, payload: dict[str, Any], model: ModelInfo) -> AsyncIterator[bytes]:
        body = self._prepare(payload, model.upstream_model or model.id)
        body["stream"] = True
        # Idle read timeout: a stalled upstream aborts instead of hanging forever.
        timeout = httpx.Timeout(
            connect=10.0,
            read=float(getattr(settings, 'request_timeout', 120) or 120),
            write=30.0,
            pool=10.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", f"{self.base_url.rstrip('/')}/chat/completions", json=body, headers=self._headers()) as r:
                if r.status_code >= 400:
                    err = (await r.aread()).decode(errors="ignore")
                    raise ProviderError(
                        f"{self.label} error {r.status_code}: {err[:350]}",
                        status=r.status_code, provider=self.id,
                        retry_after=parse_retry_after(r.headers.get("retry-after")),
                    )
                async for chunk in r.aiter_bytes():
                    if chunk:
                        yield chunk