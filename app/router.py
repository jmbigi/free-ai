from __future__ import annotations
import asyncio
import time
from typing import Any
from .providers.pollinations import PollinationsProvider
from .providers.configured import (
    GroqProvider, OpenRouterProvider, NvidiaProvider, MistralProvider,
    SambaNovaProvider, CerebrasProvider, HuggingFaceProvider, TogetherProvider, CohereProvider,
    DeepSeekProvider, MoonshotProvider, OpenCodeProvider, GenericOpenAIProvider,
)
from .providers.gemini import GeminiProvider
from .providers.cloudflare import CloudflareProvider
from .providers.base import ModelInfo, ProviderError

_COOLDOWN: dict[str, float] = {}

def _instances():
    return [
        PollinationsProvider(),
        OpenRouterProvider(), GroqProvider(), NvidiaProvider(), GeminiProvider(), CloudflareProvider(),
        MistralProvider(), SambaNovaProvider(), CerebrasProvider(), HuggingFaceProvider(),
        TogetherProvider(), CohereProvider(), DeepSeekProvider(), MoonshotProvider(), OpenCodeProvider(), GenericOpenAIProvider(),
    ]

AUTO_CANDIDATES = [
    ("pollinations", "openai-fast", "Pollinations anónimo"),
    ("openrouter", "openrouter/free", "OpenRouter router free"),
    ("openrouter", "meta-llama/llama-3.3-70b-instruct:free", "OpenRouter :free"),
    ("openrouter", "qwen/qwen3-coder:free", "OpenRouter :free"),
    ("openrouter", "google/gemma-3-27b-it:free", "OpenRouter :free"),
    ("groq", "llama-3.3-70b-versatile", "Groq"),
    ("groq", "openai/gpt-oss-20b", "Groq"),
    ("nvidia", "meta/llama-3.3-70b-instruct", "NVIDIA NIM"),
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b", "NVIDIA NIM"),
    ("gemini", "gemini-2.5-flash", "Gemini"),
    ("cloudflare", "@cf/meta/llama-3.1-8b-instruct", "Cloudflare"),
    ("mistral", "mistral-small-latest", "Mistral"),
    ("sambanova", "Meta-Llama-3.3-70B-Instruct", "SambaNova"),
    ("cerebras", "llama-3.3-70b", "Cerebras"),
    ("deepseek", "deepseek-flash", "DeepSeek official"),
    ("moonshot", "kimi-k3.1-pro", "Moonshot/Kimi"),
    ("opencode", "big-pickle", "OpenCode"),
    ("pollinations", "openai", "Pollinations anónimo"),
]

async def catalog() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    models: list[ModelInfo] = []
    providers = []
    for p in _instances():
        active = p.available()
        providers.append({"id": p.id, "label": p.label, "active": active, "always_on": p.id == "pollinations"})
        try:
            listed = await p.list_models()
        except Exception:
            listed = []
        if active or p.id == "pollinations":
            for m in listed:
                if not any(x.id == m.id for x in models):
                    models.append(m)
    auto = ModelInfo(id="auto", provider="gateway", owned_by="gateway", upstream_model="auto",
                     capabilities=["chat","fallback","retry"], note="Fallback automático con reintentos entre proveedores/cuentas configurados y gratuitos disponibles.")
    return providers, [auto.__dict__] + [m.__dict__ for m in models]

def get_provider(pid: str):
    for p in _instances():
        if p.id == pid:
            return p
    return None

async def resolve_model(model_id: str) -> tuple[Any, ModelInfo]:
    model_id = (model_id or "").strip() or "auto"
    _, models = await catalog()
    by_id = {m["id"]: m for m in models}
    if model_id == "auto":
        return get_provider("pollinations"), ModelInfo(**by_id["auto"])
    if model_id in by_id and model_id != "auto":
        m = by_id[model_id]
        p = get_provider(m["provider"])
        if p: return p, ModelInfo(**m)
    if "/" in model_id:
        prefix, rest = model_id.split("/", 1)
        p = get_provider(prefix)
        if p and (p.available() or prefix == "pollinations"):
            if model_id in by_id:
                return p, ModelInfo(**by_id[model_id])
            return p, ModelInfo(id=model_id, provider=prefix, owned_by=prefix, upstream_model=rest,
                                capabilities=["chat"], note="ID pasado directo al proveedor (útil para modelos no listados).")
    needle = model_id.lower()
    for m in models:
        if m["id"] == "auto": continue
        if needle in (m["id"].lower(), (m.get("upstream_model") or "").lower()):
            return get_provider(m["provider"]), ModelInfo(**m)
    for m in models:
        if m["id"] != "auto" and needle in m["id"].lower():
            return get_provider(m["provider"]), ModelInfo(**m)
    raise ProviderError(f"Modelo desconocido '{model_id}'. Usa GET /v1/models o pasa proveedor/modelo directo.", status=400, provider="gateway")

def _retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    status = getattr(exc, 'status', None)
    if status in (400, 401, 403, 404, 422):
        # some 400s are payload issues, but keep gateway/provider mismatch retryable only when obvious
        if any(s in msg for s in ['rate limit','quota','free limit','temporarily','retry']):
            return True
        return False
    return any(s in msg for s in ['429','402','rate limit','quota','free limit','insufficient','timeout','503','502','504','unavailable','busy','budget','not supported','model_not_supported','no endpoints','overloaded','temporar','try again'])

def _cooldown_for(exc: Exception) -> float:
    msg = str(exc).lower()
    if 'pollinations' in msg and ('45 seconds' in msg or 'free limit' in msg):
        return 46.0
    if '429' in msg or 'rate limit' in msg or 'quota' in msg:
        return 8.0
    if '402' in msg or 'insufficient' in msg or 'credit' in msg:
        return 60.0
    return 2.0

def _on_cooldown(mid: str) -> bool:
    return _COOLDOWN.get(mid, 0) > time.time()

def _mark_cooldown(mid: str, seconds: float):
    _COOLDOWN[mid] = max(_COOLDOWN.get(mid, 0), time.time() + seconds)

async def _call_with_retry(provider, model, payload, *, attempts: list[dict[str, Any]], max_attempts: int = 10):
    last_exc = None
    for i in range(max_attempts):
        if _on_cooldown(model.id) and model.provider == 'pollinations':
            # try to find any non-cooldown candidate is handled by caller; for direct call just wait short
            wait = min(3.0, max(0.2, _COOLDOWN[model.id] - time.time()))
            if i < max_attempts - 1 and wait > 0:
                await asyncio.sleep(wait)
        try:
            data = await provider.chat(payload, model)
            data.setdefault("gateway", {})
            data["gateway"]["attempts"] = attempts + [{"provider": provider.id, "model": model.id, "ok": True, "try": i + 1}]
            data["gateway"]["fallback_used"] = len(attempts) > 0
            data["gateway"]["selected"] = model.id
            data["requested_model"] = model.id
            return data
        except Exception as e:
            last_exc = e
            attempts.append({"provider": provider.id, "model": model.id, "ok": False, "try": i + 1, "error": str(e)[:300]})
            _mark_cooldown(model.id, _cooldown_for(e))
            if not _retryable(e) or i >= max_attempts - 1:
                raise
            await asyncio.sleep(min(0.6 * (2 ** min(i, 4)), 6.0))
    if last_exc:
        raise last_exc
    raise ProviderError("Sin respuesta", status=502, provider="gateway")

async def execute_with_fallback(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    requested = (payload.get("model") or "auto").strip() or "auto"
    explicit = requested != "auto"
    max_attempts = 10
    gw = payload.get('gateway') if isinstance(payload.get('gateway'), dict) else {}
    try:
        max_attempts = max(1, min(10, int(gw.get('max_retries', payload.get('max_retries', 10)))))
    except Exception:
        max_attempts = 10
    if explicit:
        provider, model = await resolve_model(requested)
        try:
            data = await _call_with_retry(provider, model, payload, attempts=list(attempts), max_attempts=max_attempts)
            return data, attempts
        except Exception as e:
            attempts = (data.get('gateway', {}).get('attempts') if 'data' in locals() and isinstance(data, dict) else attempts)
            if not attempts:
                attempts = [{"provider": getattr(provider,'id','?'), "model": getattr(model,'id',requested), "ok": False, "error": str(e)[:300]}]
            if not _retryable(e):
                raise
    tried = set(a['model'] for a in attempts)
    # build candidate list preferring not-on-cooldown
    cands = []
    for pid, upstream, label in AUTO_CANDIDATES:
        p = get_provider(pid)
        if not p or not (p.available() or pid == "pollinations"):
            continue
        mid = f"{pid}/{upstream}"
        if mid in tried: continue
        cands.append((0 if not _on_cooldown(mid) else 1, pid, upstream, label, mid, p))
    cands.sort(key=lambda x: x[0])
    for _, pid, upstream, label, mid, p in cands[:max_attempts * 2]:
        model = ModelInfo(id=mid, provider=pid, owned_by=pid, upstream_model=upstream, capabilities=["chat"], note=label)
        try:
            data = await p.chat(payload, model)
            data.setdefault("gateway", {})
            data["gateway"]["attempts"] = attempts + [{"provider": pid, "model": mid, "ok": True}]
            data["gateway"]["fallback_used"] = explicit or len(attempts) > 0
            data["gateway"]["selected"] = mid
            data["requested_model"] = requested
            return data, attempts
        except Exception as e:
            attempts.append({"provider": pid, "model": mid, "ok": False, "error": str(e)[:300]})
            _mark_cooldown(mid, _cooldown_for(e))
            continue
        if len([a for a in attempts if not a.get('ok')]) >= max_attempts:
            break
    detail = " | ".join(a["provider"]+"/"+a["model"].split('/',1)[-1]+": "+a["error"] for a in attempts[-6:]) or "Sin proveedores disponibles"
    raise ProviderError(f"Todos los proveedores/cuentas disponibles fallaron o están limitados. Intentos: {detail}", status=502, provider="gateway")

async def stream_with_fallback(payload: dict[str, Any]):
    requested = (payload.get("model") or "auto").strip() or "auto"
    candidates = []
    if requested != "auto":
        try:
            p,m = await resolve_model(requested); candidates.append((p,m))
        except Exception: pass
    for pid, upstream, _ in AUTO_CANDIDATES:
        p=get_provider(pid)
        if not p or not (p.available() or pid=='pollinations'): continue
        m=ModelInfo(id=f"{pid}/{upstream}", provider=pid, owned_by=pid, upstream_model=upstream, capabilities=["chat"])
        if not any(x[1].id==m.id for x in candidates): candidates.append((p,m))
    errors=[]
    for p,m in candidates[:10]:
        if _on_cooldown(m.id): continue
        try:
            async for chunk in p.stream_chat(payload, m): yield chunk
            return
        except Exception as e:
            errors.append(f"{m.id}: {str(e)[:220]}"); _mark_cooldown(m.id, _cooldown_for(e)); continue
    raise ProviderError("Streaming fallback agotado: " + " | ".join(errors[-4:]), status=502, provider="gateway")
