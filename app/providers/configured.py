from __future__ import annotations
import json
import time
import uuid

import httpx

from .openai_compat import OpenAICompatProvider
from .base import ModelInfo, ProviderError, parse_retry_after
from .ollama_tools import build_completion, stream_delta, to_ollama_messages
from .llamacpp_tools import extract_content_tool_calls, openai_tool_calls, to_llamacpp_messages
from ..config import settings
from ..normalize import normalize_chat_response

class _S(OpenAICompatProvider):
    @property
    def api_key(self): return ""
    @api_key.setter
    def api_key(self, v): pass

class GroqProvider(_S):
    id = "groq"; label = "Groq (free tier when key configured)"
    base_url = "https://api.groq.com/openai/v1"
    @property
    def api_key(self): return settings.groq_api_key
    default_models = [
        ("llama-3.3-70b-versatile", "llama-3.3-70b-versatile", ["chat","tools"], "Groq free tier; limits vary by model/plan."),
        ("openai/gpt-oss-120b", "openai/gpt-oss-120b", ["chat"], "Groq open-weight model; check account limits."),
        ("openai/gpt-oss-20b", "openai/gpt-oss-20b", ["chat"], "Groq open-weight model; check account limits."),
        ("qwen/qwen3-32b", "qwen/qwen3-32b", ["chat"], "Groq hosted model; check account limits."),
    ]

class OpenRouterProvider(_S):
    id = "openrouter"; label = "OpenRouter (key configurada; rutas :free/auto según cuota)"
    base_url = "https://openrouter.ai/api/v1"
    extra_headers = {"HTTP-Referer": "http://localhost:8000", "X-Title": "Free AI Gateway"}
    @property
    def api_key(self): return settings.openrouter_api_key

    async def list_models(self):
        base = await super().list_models()
        seen = {m.upstream_model for m in base}
        if not self.available():
            return base
        try:
            import httpx
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.get(f"{self.base_url}/models", headers=self._headers())
                if r.status_code == 200:
                    for m in (r.json().get('data') or []):
                        mid = (m.get('id') or '').strip()
                        if not mid or ':free' not in mid or mid in seen:
                            continue
                        seen.add(mid)
                        caps = ['chat']
                        name = (m.get('name') or mid).lower()
                        if 'coder' in name or 'code' in name or 'tool' in str(m.get('supported_parameters') or []):
                            caps.append('tools')
                        from .base import ModelInfo
                        base.append(ModelInfo(id=f"{self.id}/{mid}", provider=self.id, owned_by=(m.get('owned_by') or self.id), upstream_model=mid, capabilities=caps, note='OpenRouter :free discovered from /models (quota/rate limits/capacity vary).'))
        except Exception as e:
            import logging
            logging.getLogger("free-ai.providers").warning("OpenRouter :free discovery failed: %s", e)
        return base

    default_models = [
        ("openrouter/free", "openrouter/free", ["chat"], "Routes to available eligible free models; availability/rate limits vary."),
        ("meta-llama/llama-3.3-70b-instruct:free", "meta-llama/llama-3.3-70b-instruct:free", ["chat","tools"], "Free variant when available."),
        ("qwen/qwen3-coder:free", "qwen/qwen3-coder:free", ["chat","tools"], "Free variant when available."),
        ("google/gemma-3-27b-it:free", "google/gemma-3-27b-it:free", ["chat","tools"], "Free variant when available."),
        ("google/gemma-4-31b-it:free", "google/gemma-4-31b-it:free", ["chat","tools"], "OpenRouter :free (verified in /models catalog when key configured)."),
        ("google/gemma-4-26b-a4b-it:free", "google/gemma-4-26b-a4b-it:free", ["chat","tools"], "OpenRouter :free (availability/rate limits vary)."),
        ("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", ["chat","reasoning"], "OpenRouter :free; limits vary."),
        ("liquid/lfm-2.5-2.6b:free", "liquid/lfm-2.5-2.6b:free", ["chat"], "OpenRouter :free small model; limits vary."),
    ]

class NvidiaProvider(_S):
    id = "nvidia"; label = "NVIDIA NIM (free tier when key configured)"
    base_url = "https://integrate.api.nvidia.com/v1"
    @property
    def api_key(self): return settings.nvidia_api_key
    default_models = [
        ("meta/llama-3.3-70b-instruct", "meta/llama-3.3-70b-instruct", ["chat"], "NVIDIA hosted; availability/limits may change."),
        ("nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-super-120b-a12b", ["chat"], "NVIDIA Nemotron; availability may change."),
        ("deepseek-ai/deepseek-v3.2", "deepseek-ai/deepseek-v3.2", ["chat","reasoning"], "Hosted via NVIDIA NIM when available."),
    ]

class MistralProvider(_S):
    id = "mistral"; label = "Mistral (tier/experiment when key configured)"
    base_url = "https://api.mistral.ai/v1"
    @property
    def api_key(self): return settings.mistral_api_key
    default_models = [("mistral-small-latest", "mistral-small-latest", ["chat"], "Mistral model; limits depend on account plan.")]

class SambaNovaProvider(_S):
    id = "sambanova"; label = "SambaNova (free tier when key configured)"
    base_url = "https://api.sambanova.ai/v1"
    @property
    def api_key(self): return settings.sambanova_api_key
    default_models = [("Meta-Llama-3.3-70B-Instruct", "Meta-Llama-3.3-70B-Instruct", ["chat"], "Free tier limits apply.")]

class CerebrasProvider(_S):
    id = "cerebras"; label = "Cerebras (when key configured)"
    base_url = "https://api.cerebras.ai/v1"
    @property
    def api_key(self): return settings.cerebras_api_key
    default_models = [("llama-3.3-70b", "llama-3.3-70b", ["chat"], "Requires Cerebras API key; limits/credits apply.")]

class HuggingFaceProvider(_S):
    id = "huggingface"; label = "Hugging Face Router (key configurada; requiere créditos/proveedores habilitados)"
    base_url = "https://router.huggingface.co/v1"
    @property
    def api_key(self): return settings.huggingface_api_key
    default_models = [
        ("openai/gpt-oss-20b", "openai/gpt-oss-20b", ["chat"], "HF router; requiere créditos/proveedores habilitados en la cuenta HF."),
        ("openai/gpt-oss-120b", "openai/gpt-oss-120b", ["chat"], "HF router; requiere créditos/proveedores habilitados en la cuenta HF."),
        ("Qwen/Qwen3-Coder-480B-A35B-Instruct", "Qwen/Qwen3-Coder-480B-A35B-Instruct", ["chat","tools"], "HF router; disponibilidad según cuenta."),
    ]

class TogetherProvider(_S):
    id = "together"; label = "Together (when key configured)"
    base_url = "https://api.together.xyz/v1"
    @property
    def api_key(self): return settings.together_api_key
    default_models = []

class CohereProvider(_S):
    id = "cohere"; label = "Cohere compatibility (when key configured)"
    base_url = "https://api.cohere.ai/compatibility/v1"
    @property
    def api_key(self): return settings.cohere_api_key
    default_models = [("command-r7b-12-2024", "command-r7b-12-2024", ["chat"], "Cohere compatibility endpoint; trial limits apply.")]

class DeepSeekProvider(_S):
    id = "deepseek"; label = "DeepSeek official API (when key configured; pay-as-you-go/credits)"
    base_url = "https://api.deepseek.com"
    @property
    def api_key(self): return settings.deepseek_api_key
    default_models = [
        ("deepseek-flash", "deepseek-flash", ["chat","reasoning"], "DeepSeek official model; requires DeepSeek API key/balance."),
        ("deepseek-v4-pro", "deepseek-v4-pro", ["chat","reasoning"], "DeepSeek official model; requires DeepSeek API key/balance."),
    ]

class MoonshotProvider(_S):
    id = "moonshot"; label = "Moonshot/Kimi Open Platform (OpenAI-compatible; when key configured)"
    base_url = "https://api.moonshot.ai/v1"
    extra_headers = {}
    @property
    def api_key(self): return settings.moonshot_api_key or settings.kimi_api_key
    default_models = [
        ("kimi-k3.1-pro", "kimi-k3.1-pro", ["chat"], "Moonshot/Kimi Open Platform model; account access/quota applies."),
        ("kimi-k2.5", "kimi-k2.5", ["chat"], "Moonshot/Kimi model id (availability depends on account)."),
    ]

class OpenCodeProvider(_S):
    id = "opencode"; label = "OpenCode inference (when key configured; free/paid availability may vary)"
    @property
    def base_url(self): return settings.opencode_base_url or "https://opencode.ai/inference/openai/v1"
    @property
    def api_key(self): return settings.opencode_api_key
    default_models = [
        ("big-pickle", "big-pickle", ["chat"], "OpenCode model; access/limits depend on OpenCode account/product and may rotate."),
        ("deepseek-v4.1-flash-free", "deepseek-v4.1-flash-free", ["chat"], "OpenCode free-tier model when available; may be app/region/rotation limited."),
        ("glm-5.3-flash-free", "glm-5.3-flash-free", ["chat"], "OpenCode free-tier model when available; may rotate."),
    ]

class GenericOpenAIProvider(_S):
    id = "openai-compatible"; label = "Custom OpenAI-compatible upstream (BASE_URL+API_KEY)"
    @property
    def base_url(self): return settings.openai_compatible_base_url
    @property
    def api_key(self): return settings.openai_compatible_api_key
    default_models = [
        ("default", "gpt-4o-mini", ["chat"], "Pass a concrete model id as openai-compatible/<model> when using a custom upstream."),
    ]


class NCMLm1bProvider(_S):
    """Official NCM LM1B-large: unconditional 128-token generation; ignores prompts."""
    id = "ncm-lm1b"; label = "NCM LM1B-large local (unconditional; ignores prompt)"
    @property
    def base_url(self): return settings.ncm_lm1b_base_url
    @property
    def api_key(self): return "local" if settings.ncm_lm1b_enabled else ""
    def available(self): return bool(settings.ncm_lm1b_enabled and self.base_url)
    @property
    def default_models(self):
        m = settings.ncm_lm1b_model
        return [(m, m, ["chat"], "Official NCM LM1B-large; unconditional, fixed 128 tokens, ignores prompts.")]

    async def list_models(self):
        m = settings.ncm_lm1b_model
        return [ModelInfo(
            id=f"{self.id}/{m}", provider=self.id, owned_by=self.id,
            upstream_model=m, capabilities=["chat"],
            note="Official NCM LM1B-large; unconditional, fixed 128 tokens; ignores prompts.",
        )]


class OllamaLocalProvider(_S):
    """Local Ollama OpenAI-compatible endpoint (Qwen3.5-9B or configured model)."""
    id = "local-ollama"; label = "Qwen3.5-9B local (Ollama, experimental fallback)"
    @property
    def base_url(self): return settings.local_ollama_base_url
    @property
    def api_key(self): return "ollama" if settings.local_ollama_enabled else ""
    def available(self): return bool(settings.local_ollama_enabled and self.base_url)
    @property
    def default_models(self):
        m = settings.local_ollama_model
        return [(m, m, ["chat", "tools"], "Local Ollama model; tools when the selected model supports them; experimental fallback.")]

    async def list_models(self):
        # Expose only the configured safe model. Other local models can still be
        # requested explicitly as local-ollama/<model>, but are not auto-listed
        # (an 18GB model would OOM this 8GB GPU).
        m = settings.local_ollama_model
        return [ModelInfo(
            id=f"{self.id}/{m}", provider=self.id, owned_by=self.id,
            upstream_model=m, capabilities=["chat", "tools"],
            note="Configured local Ollama fallback; tool support depends on the model.",
        )]

    def _native_url(self) -> str:
        base = self.base_url.removesuffix("/v1").rstrip("/")
        return f"{base}/api/chat"

    def _body(self, payload, model) -> dict:
        requested = int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 0)
        minimum = int(getattr(settings, "local_ollama_min_tokens", 512) or 512)
        num_predict = max(requested, minimum) if requested else minimum
        body = {
            "model": model.upstream_model or model.id,
            "messages": to_ollama_messages(payload.get("messages") or []),
            "stream": False,
            "think": bool(settings.local_ollama_think),
            "options": {
                "num_ctx": int(settings.local_ollama_ctx),
                "num_predict": num_predict,
                "temperature": float(payload.get("temperature") or 0),
                "top_p": float(payload.get("top_p") or 1.0),
            },
        }
        if payload.get("stop"):
            body["options"]["stop"] = payload["stop"]
        if payload.get("tools"):
            body["tools"] = payload["tools"]
        if payload.get("tool_choice"):
            body["tool_choice"] = payload["tool_choice"]
        return body

    async def chat(self, payload, model):
        body = self._body(payload, model)
        timeout = httpx.Timeout(float(getattr(settings, "request_timeout", 120) or 120), connect=8.0)
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(self._native_url(), json=body)
        if r.status_code >= 400:
            raise ProviderError(
                f"Ollama error {r.status_code}: {r.text[:350]}",
                status=r.status_code, provider=self.id,
                retry_after=parse_retry_after(r.headers.get("retry-after")),
            )
        data = r.json()
        msg = data.get("message") or {}
        content = msg.get("content")
        thinking = msg.get("thinking")
        tool_calls = msg.get("tool_calls") or []
        if not content and not tool_calls and thinking:
            raise ProviderError(
                "Ollama returned only thinking; set LOCAL_OLLAMA_THINK=0 or increase tokens.",
                status=502, provider=self.id,
            )
        if not content and not tool_calls:
            raise ProviderError("Ollama returned empty content", status=502, provider=self.id)
        out = build_completion(
            model=body["model"],
            content=content,
            thinking=thinking,
            raw_tool_calls=tool_calls,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            completion_id=f"chatcmpl-ollama-{uuid.uuid4().hex[:16]}",
            created=int(time.time()),
            provider=self.id,
            gateway_extra={
                "think": bool(settings.local_ollama_think),
                "num_ctx": int(settings.local_ollama_ctx),
                "num_predict": int(body["options"]["num_predict"]),
            },
        )
        out["requested_model"] = model.id
        return out

    async def stream_chat(self, payload, model):
        body = self._body(payload, model)
        body["stream"] = True
        stream_id = f"chatcmpl-ollama-{uuid.uuid4().hex[:16]}"
        created = int(time.time())
        timeout = httpx.Timeout(
            connect=10.0,
            read=float(getattr(settings, "request_timeout", 120) or 120),
            write=30.0,
            pool=10.0,
        )
        async with httpx.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", self._native_url(), json=body) as r:
                if r.status_code >= 400:
                    err = (await r.aread()).decode(errors="ignore")
                    raise ProviderError(
                        f"Ollama error {r.status_code}: {err[:350]}",
                        status=r.status_code, provider=self.id,
                    )
                done_seen = False
                tool_calls_seen = False
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(
                            f"Ollama stream returned invalid JSON: {line[:120]}",
                            status=502, provider=self.id,
                        ) from exc
                    msg = data.get("message") or {}
                    delta = stream_delta(
                        content=msg.get("content"),
                        thinking=msg.get("thinking"),
                        raw_tool_calls=msg.get("tool_calls") or [],
                    )
                    if len(delta) > 1:
                        if "tool_calls" in delta:
                            tool_calls_seen = True
                        chunk = {
                            "id": stream_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": body["model"],
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
                    if data.get("done"):
                        done_seen = True
                        final = {
                            "id": stream_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": body["model"],
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool_calls_seen else "stop"}],
                        }
                        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return
                if not done_seen:
                    raise ProviderError(
                        "Ollama stream ended without done marker",
                        status=502, provider=self.id,
                    )


class LlamaCppLocalProvider(_S):
    """Optional llama-cpp-python OpenAI-compatible local server.

    llama.cpp's Qwen3-Coder GGUF template emits XML tool calls as text.  This
    provider converts them to OpenAI ``tool_calls`` and converts tool-call
    argument strings back to mappings for the template.  Tool-bearing requests
    are buffered (non-stream upstream) so the XML is never leaked to clients;
    plain text requests keep the upstream stream.
    """
    id = "local-llamacpp"; label = "Qwen3-Coder local (llama-cpp-python, optional)"

    @property
    def base_url(self): return settings.local_llamacpp_base_url

    @property
    def api_key(self): return "local" if settings.local_llamacpp_enabled else ""

    def available(self): return bool(settings.local_llamacpp_enabled and self.base_url)

    @property
    def default_models(self):
        m = settings.local_llamacpp_model
        return [(m, m, ["chat", "tools"], "Local llama.cpp GGUF; tools via XML parsing; optional backend.")]

    async def list_models(self):
        m = settings.local_llamacpp_model
        return [ModelInfo(
            id=f"{self.id}/{m}", provider=self.id, owned_by=self.id,
            upstream_model=m, capabilities=["chat", "tools"],
            note="Optional llama-cpp-python local backend; tool support via XML parsing.",
        )]

    def _prepare(self, payload: dict, upstream: str) -> dict:
        body = super()._prepare(payload, upstream)
        body["messages"] = to_llamacpp_messages(body.get("messages") or [])
        return body

    @staticmethod
    def _convert_response(data: dict, model_id: str, provider: str, allow_bare_json: bool = False) -> dict:
        choices = data.get("choices") if isinstance(data, dict) else None
        total_calls = 0
        for ch in choices or []:
            if not isinstance(ch, dict):
                continue
            msg = ch.get("message") if isinstance(ch.get("message"), dict) else None
            if msg is None:
                continue
            calls = openai_tool_calls(msg.get("tool_calls") or [])
            clean, content_calls = extract_content_tool_calls(msg.get("content"), allow_bare_json=allow_bare_json)
            calls.extend(content_calls)
            if calls:
                msg["content"] = clean
                msg["tool_calls"] = calls
                ch["finish_reason"] = "tool_calls"
                total_calls += len(calls)
        if isinstance(data, dict):
            data["provider"] = provider
            data["requested_model"] = model_id
            gw = data.get("gateway") if isinstance(data.get("gateway"), dict) else {}
            gw.update({"local": True, "llamacpp": True, "tool_calls": total_calls})
            data["gateway"] = gw
        return normalize_chat_response(data)

    async def chat(self, payload: dict, model: ModelInfo) -> dict:
        body = self._prepare(payload, model.upstream_model or model.id)
        body["stream"] = False
        timeout = httpx.Timeout(float(settings.local_llamacpp_timeout), connect=8.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=body, headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.label} connection error: {exc}",
                status=502, provider=self.id,
            ) from exc
        if r.status_code >= 400:
            raise ProviderError(
                f"{self.label} error {r.status_code}: {r.text[:350]}",
                status=r.status_code, provider=self.id,
                retry_after=parse_retry_after(r.headers.get("retry-after")),
            )
        data = r.json()
        return self._convert_response(data, model.id, self.id, allow_bare_json=bool(payload.get("tools")))

    async def stream_chat(self, payload: dict, model: ModelInfo):
        # Tool calls are parsed from the complete XML block, so use a buffered
        # completion and emit a valid OpenAI SSE sequence.  This avoids leaking
        # raw <tool_call> XML into agent clients.
        if not payload.get("tools"):
            async for chunk in super().stream_chat(payload, model):
                yield chunk
            return
        data = await self.chat(payload, model)
        ch = (data.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        content = msg.get("content") or ""
        calls = msg.get("tool_calls") or []
        stream_id = data.get("id") or f"chatcmpl-llamacpp-{uuid.uuid4().hex[:16]}"
        created = int(data.get("created") or time.time())
        model_name = data.get("model") or model.id

        def event(delta: dict, finish=None, usage=None) -> bytes:
            obj = {
                "id": stream_id, "object": "chat.completion.chunk",
                "created": created, "model": model_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            if usage is not None:
                obj["usage"] = usage
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()

        yield event({"role": "assistant", "content": content} if content else {"role": "assistant"})
        if calls:
            indexed = []
            for idx, call in enumerate(calls):
                call = dict(call)
                call["index"] = idx
                indexed.append(call)
            yield event({"tool_calls": indexed})
            yield event({}, "tool_calls", data.get("usage"))
        else:
            yield event({}, "stop", data.get("usage"))
        yield b"data: [DONE]\n\n"


class NCMProvider(_S):
    """Local NCM-Instruct-725M (experimental, 128-token context, CC BY-NC-SA)."""
    id = "ncm"; label = "NCM-Instruct 725M local (experimental, thinker-lite)"
    @property
    def base_url(self): return settings.ncm_local_base_url
    @property
    def api_key(self): return "local" if settings.ncm_local_enabled else ""
    def available(self): return bool(settings.ncm_local_enabled and self.base_url)
    @property
    def default_models(self):
        m = settings.ncm_local_model
        return [(m, m, ["chat"], "Local NCM-Instruct-725M experimental; 128-token context; CC BY-NC-SA 4.0; thinker-lite layer.")]


class LLM7Provider(_S):
    """LLM7.io - key optional (best-effort). Free availability/rate limits/model rotation vary; verify before relying."""
    id = "llm7"; label = "LLM7 (key opcional; best-effort, disponibilidad/capacidad free varía)"
    @property
    def base_url(self): return getattr(settings,'llm7_base_url',None) or 'https://api.llm7.io/v1'
    @property
    def api_key(self): return getattr(settings,'llm7_api_key','') or 'unused'
    def available(self): return True  # key optional; actual availability verified per request
    default_models = [
        ("default", "default", ["chat"], "LLM7 default route; availability/rate limits vary."),
    ]
    async def list_models(self):
        # try discover; keep conservative
        try:
            base = await super().list_models()
            if base: return base
        except Exception as e:
            import logging
            logging.getLogger("free-ai.providers").warning("LLM7 list_models failed: %s", e)
        return [__import__('app.providers.base',fromlist=['ModelInfo']).ModelInfo(id=f"{self.id}/default", provider=self.id, owned_by=self.id, upstream_model="default", capabilities=["chat"], note="LLM7 key-optional endpoint; model availability/rate limits may vary.")]
