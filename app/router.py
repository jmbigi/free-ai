from __future__ import annotations
from typing import Any
from .providers.pollinations import PollinationsProvider
from .providers.configured import (
    GroqProvider, OpenRouterProvider, NvidiaProvider, MistralProvider,
    SambaNovaProvider, CerebrasProvider, HuggingFaceProvider, TogetherProvider, CohereProvider,
)
from .providers.gemini import GeminiProvider
from .providers.cloudflare import CloudflareProvider
from .providers.base import ModelInfo, ProviderError

def _instances():
    return [
        PollinationsProvider(),
        GroqProvider(), OpenRouterProvider(), GeminiProvider(), CloudflareProvider(),
        NvidiaProvider(), MistralProvider(), SambaNovaProvider(), CerebrasProvider(),
        HuggingFaceProvider(), TogetherProvider(), CohereProvider(),
    ]

AUTO_CANDIDATES = [
    ("pollinations", "openai-fast", "Pollinations anónimo"),
    ("pollinations", "openai", "Pollinations anónimo"),
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
                     capabilities=["chat","fallback"], note="Fallback automático entre proveedores/cuentas gratuitos disponibles.")
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
    return any(s in msg for s in ['429','rate limit','quota','402','payment','credit','insufficient','timeout','503','502','504','unavailable','busy','budget','not supported','model_not_supported','no endpoints','403','temporarily'])

async def execute_with_fallback(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    requested = (payload.get("model") or "auto").strip() or "auto"
    explicit = requested != "auto"
    if explicit:
        provider, model = await resolve_model(requested)
        try:
            data = await provider.chat(payload, model)
            data.setdefault("gateway", {})
            data["gateway"]["attempts"] = [{"provider": provider.id, "model": model.id, "ok": True}]
            data["gateway"]["fallback_used"] = False
            data["requested_model"] = model.id
            return data, attempts
        except Exception as e:
            attempts.append({"provider": getattr(provider,'id','?'), "model": getattr(model,'id',requested), "ok": False, "error": str(e)[:350]})
            if not _retryable(e):
                raise
    tried = set(a['model'] for a in attempts)
    for pid, upstream, label in AUTO_CANDIDATES:
        p = get_provider(pid)
        if not p or not (p.available() or pid == "pollinations"):
            continue
        mid = f"{pid}/{upstream}"
        if mid in tried:
            continue
        tried.add(mid)
        model = ModelInfo(id=mid, provider=pid, owned_by=pid, upstream_model=upstream, capabilities=["chat"], note=label)
        try:
            data = await p.chat(payload, model)
            data.setdefault("gateway", {})
            data["gateway"]["attempts"] = attempts + [{"provider": pid, "model": mid, "ok": True}]
            data["gateway"]["fallback_used"] = explicit or len(attempts) > 0
            data["gateway"]["selected"] = mid
            return data, attempts
        except Exception as e:
            attempts.append({"provider": pid, "model": mid, "ok": False, "error": str(e)[:350]})
            continue
    detail = " | ".join(a["provider"]+"/"+a["model"].split('/',1)[-1]+": "+a["error"] for a in attempts[-5:]) or "Sin proveedores disponibles"
    raise ProviderError(f"Todos los proveedores/cuentas disponibles fallaron o están limitados. Intentos: {detail}", status=502, provider="gateway")

async def stream_with_fallback(payload: dict[str, Any]):
    requested = (payload.get("model") or "auto").strip() or "auto"
    candidates = []
    if requested != "auto":
        try:
            p,m = await resolve_model(requested)
            candidates.append((p,m))
        except Exception:
            pass
    for pid, upstream, _ in AUTO_CANDIDATES:
        p=get_provider(pid)
        if not p or not (p.available() or pid=='pollinations'): continue
        m=ModelInfo(id=f"{pid}/{upstream}", provider=pid, owned_by=pid, upstream_model=upstream, capabilities=["chat"])
        if not any(x[1].id==m.id for x in candidates): candidates.append((p,m))
    errors=[]
    for p,m in candidates:
        try:
            async for chunk in p.stream_chat(payload, m):
                yield chunk
            return
        except Exception as e:
            errors.append(f"{m.id}: {str(e)[:220]}")
            if not _retryable(e) and requested != 'auto':
                raise
            continue
    raise ProviderError("Streaming fallback agotado: " + " | ".join(errors[-3:]), status=502, provider="gateway")
