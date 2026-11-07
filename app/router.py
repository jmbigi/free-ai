from __future__ import annotations
import asyncio
import time
from typing import Any, AsyncIterator
from .providers.pollinations import PollinationsProvider
from .providers.configured import (
    GroqProvider, OpenRouterProvider, NvidiaProvider, MistralProvider,
    SambaNovaProvider, CerebrasProvider, HuggingFaceProvider, TogetherProvider, CohereProvider,
    DeepSeekProvider, MoonshotProvider, OpenCodeProvider, GenericOpenAIProvider,
)
from .providers.gemini import GeminiProvider
from .providers.cloudflare import CloudflareProvider
from .providers.base import ModelInfo, ProviderError

# mid -> unix cooldown-until
_COOLDOWN: dict[str, float] = {}
# provider_id -> {ok,fail,last_ok,last_fail,last_error,latency_ms}
_STATS: dict[str, dict[str, Any]] = {}


def _instances():
    return [
        PollinationsProvider(),
        OpenRouterProvider(), GroqProvider(), NvidiaProvider(), GeminiProvider(), CloudflareProvider(),
        MistralProvider(), SambaNovaProvider(), CerebrasProvider(), HuggingFaceProvider(),
        TogetherProvider(), CohereProvider(), DeepSeekProvider(), MoonshotProvider(), OpenCodeProvider(), GenericOpenAIProvider(),
    ]

# Ordered fallback candidates. Only active/configured providers are used (except pollinations).
# Keep free/anonymous-friendly candidates first; provider+model combos are tried with cooldown awareness.
AUTO_CANDIDATES = [
    ("pollinations", "openai-fast", "Pollinations anónimo"),
    ("openrouter", "openrouter/free", "OpenRouter router free"),
    ("openrouter", "meta-llama/llama-3.3-70b-instruct:free", "OpenRouter :free"),
    ("openrouter", "qwen/qwen3-coder:free", "OpenRouter :free"),
    ("openrouter", "google/gemma-3-27b-it:free", "OpenRouter :free"),
    ("groq", "llama-3.3-70b-versatile", "Groq"),
    ("nvidia", "meta/llama-3.3-70b-instruct", "NVIDIA NIM"),
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b", "NVIDIA NIM"),
    ("gemini", "gemini-2.5-flash", "Gemini"),
    ("cloudflare", "@cf/meta/llama-3.1-8b-instruct", "Cloudflare"),
    ("mistral", "mistral-small-latest", "Mistral"),
    ("sambanova", "Meta-Llama-3.3-70B-Instruct", "SambaNova"),
    ("cerebras", "llama-3.3-70b", "Cerebras"),
    ("huggingface", "meta-llama/Llama-3.3-70B-Instruct", "Hugging Face"),
    ("deepseek", "deepseek-chat", "DeepSeek official"),
    ("moonshot", "kimi-k2-0711-preview", "Moonshot/Kimi"),
    ("opencode", "big-pickle", "OpenCode"),
    ("pollinations", "openai", "Pollinations anónimo"),
    ("openrouter", "stepfun/step-3.5-flash:free", "OpenRouter :free"),
]


def _stat(pid: str) -> dict[str, Any]:
    return _STATS.setdefault(pid, {"ok": 0, "fail": 0, "last_ok": None, "last_fail": None, "last_error": "", "latency_ms": None})


def _record(pid: str, *, ok: bool, ms: int | None = None, error: str = ""):
    s = _stat(pid)
    s["ok" if ok else "fail"] += 1
    s["last_" + ("ok" if ok else "fail")] = int(time.time())
    if ms is not None:
        s["latency_ms"] = ms
    if error:
        s["last_error"] = error[:300]


def runtime_status() -> dict[str, Any]:
    now = time.time()
    cds = {k: round(v - now, 1) for k, v in _COOLDOWN.items() if v > now}
    return {"cooldowns": cds, "stats": _STATS, "auto_candidates": len(AUTO_CANDIDATES)}


async def catalog() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    models: list[ModelInfo] = []
    providers = []
    for p in _instances():
        active = p.available()
        st = dict(_stat(p.id))
        providers.append({"id": p.id, "label": p.label, "active": active, "always_on": p.id == "pollinations", "stats": st})
        try:
            listed = await p.list_models()
        except Exception:
            listed = []
        if active or p.id == "pollinations":
            for m in listed:
                if not any(x.id == m.id for x in models):
                    models.append(m)
    auto = ModelInfo(
        id="auto", provider="gateway", owned_by="gateway", upstream_model="auto",
        capabilities=["chat", "fallback", "retry", "cache-aware"],
        note="Fallback automático con reintentos/cooldowns entre proveedores/cuentas configurados y gratuitos disponibles. No garantiza inferencia ilimitada: los tiers gratuitos tienen cuotas/rate limits.",
    )
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
        if p:
            return p, ModelInfo(**m)
    if "/" in model_id:
        prefix, rest = model_id.split("/", 1)
        p = get_provider(prefix)
        if p and (p.available() or prefix == "pollinations"):
            if model_id in by_id:
                return p, ModelInfo(**by_id[model_id])
            return p, ModelInfo(
                id=model_id, provider=prefix, owned_by=prefix, upstream_model=rest,
                capabilities=["chat"], note="ID pasado directo al proveedor (útil para modelos no listados).",
            )
    needle = model_id.lower()
    for m in models:
        if m["id"] == "auto":
            continue
        if needle in (m["id"].lower(), (m.get("upstream_model") or "").lower()):
            return get_provider(m["provider"]), ModelInfo(**m)
    for m in models:
        if m["id"] != "auto" and needle in m["id"].lower():
            return get_provider(m["provider"]), ModelInfo(**m)
    raise ProviderError(f"Modelo desconocido '{model_id}'. Usa GET /v1/models o pasa proveedor/modelo directo.", status=400, provider="gateway")


def _retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    status = getattr(exc, 'status', None)
    if status in (401, 403, 404):
        if any(s in msg for s in ['quota', 'rate limit', 'free limit', 'credit', 'insufficient', 'provider', 'temporar']):
            return True
        return False
    if status == 400:
        return any(s in msg for s in ['rate limit', 'quota', 'free limit', 'temporar', 'retry', 'model', 'not supported'])
    if status in (408, 409, 425, 429, 402, 500, 502, 503, 504):
        return True
    return any(s in msg for s in [
        '429', '402', 'rate limit', 'quota', 'free limit', 'insufficient', 'timeout', 'timed out',
        '503', '502', '504', 'unavailable', 'busy', 'budget', 'not supported', 'model_not_supported',
        'no endpoints', 'overloaded', 'temporar', 'try again', 'connection', 'reset', 'capacity',
    ])


def _cooldown_for(exc: Exception) -> float:
    msg = str(exc).lower()
    status = getattr(exc, 'status', None)
    if 'pollinations' in msg and ('45 seconds' in msg or 'free limit' in msg or 'every 45' in msg):
        return 46.0
    if status == 402 or 'insufficient' in msg or 'credit' in msg or 'balance' in msg or 'budget' in msg:
        return 120.0
    if status == 429 or '429' in msg or 'rate limit' in msg or 'quota' in msg or 'free limit' in msg:
        # OpenRouter daily free quota can be long-lived; keep modest to allow other candidates now.
        if 'per-day' in msg or 'daily' in msg:
            return 300.0
        return 20.0
    if status in (500, 502, 503, 504) or 'unavailable' in msg or 'overloaded' in msg or 'timeout' in msg:
        return 8.0
    return 3.0


def _on_cooldown(mid: str) -> bool:
    return _COOLDOWN.get(mid, 0) > time.time()


def _cooldown_left(mid: str) -> float:
    return max(0.0, _COOLDOWN.get(mid, 0) - time.time())


def _mark_cooldown(mid: str, seconds: float):
    _COOLDOWN[mid] = max(_COOLDOWN.get(mid, 0), time.time() + max(0.5, seconds))


def _clamp_attempts(payload: dict[str, Any]) -> int:
    gw = payload.get('gateway') if isinstance(payload.get('gateway'), dict) else {}
    for src in (gw, payload):
        if 'max_retries' in src or 'retries' in src:
            try:
                return max(1, min(10, int(src.get('max_retries', src.get('retries', 10)))))
            except Exception:
                break
    return 10


def _build_auto_plan(*, exclude: set[str], max_items: int) -> list[tuple[Any, ModelInfo]]:
    plan: list[tuple[Any, ModelInfo]] = []
    scored = []
    for pid, upstream, label in AUTO_CANDIDATES:
        p = get_provider(pid)
        if not p or not (p.available() or pid == "pollinations"):
            continue
        mid = f"{pid}/{upstream}"
        if mid in exclude:
            continue
        left = _cooldown_left(mid)
        # prefer non-cooldown and historically healthier providers
        st = _stat(pid)
        health = st["ok"] - st["fail"] * 0.5
        score = (1 if left > 0 else 0, left, -health)
        scored.append((score, p, ModelInfo(id=mid, provider=pid, owned_by=pid, upstream_model=upstream, capabilities=["chat"], note=label), mid))
    scored.sort(key=lambda x: x[0])
    for _, p, m, mid in scored[:max_items]:
        plan.append((p, m))
    return plan


async def execute_with_fallback(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    requested = (payload.get("model") or "auto").strip() or "auto"
    max_attempts = _clamp_attempts(payload)
    tried: set[str] = set()

    async def try_one(provider, model) -> dict[str, Any] | None:
        t0 = time.time()
        try:
            data = await provider.chat(payload, model)
            ms = int((time.time() - t0) * 1000)
            _record(provider.id, ok=True, ms=ms)
            attempts.append({"provider": provider.id, "model": model.id, "ok": True, "ms": ms})
            data.setdefault("gateway", {})
            data["gateway"]["attempts"] = attempts
            data["gateway"]["fallback_used"] = requested != model.id and (requested != 'auto' or len(attempts) > 1)
            data["gateway"]["selected"] = model.id
            data["requested_model"] = requested
            return data
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            err = str(e)[:320]
            _record(provider.id, ok=False, ms=ms, error=err)
            _mark_cooldown(model.id, _cooldown_for(e))
            attempts.append({"provider": provider.id, "model": model.id, "ok": False, "ms": ms, "error": err, "retryable": _retryable(e)})
            return None

    if requested != "auto":
        provider, model = await resolve_model(requested)
        tried.add(model.id)
        data = await try_one(provider, model)
        if data:
            return data, attempts
        last = attempts[-1] if attempts else {}
        if not last.get("retryable", True):
            detail = last.get("error") or "Solicitud rechazada por el proveedor"
            raise ProviderError(f"{provider.id}/{model.upstream_model}: {detail}", status=getattr(provider, 'last_status', 502) or 502, provider=provider.id)

    # auto/fallback plan: try up to max_attempts distinct candidates, skipping long cooldowns when possible
    for provider, model in _build_auto_plan(exclude=tried, max_items=max_attempts * 3):
        if len([a for a in attempts if not a.get('ok')]) >= max_attempts:
            break
        if _cooldown_left(model.id) > 15 and any(p.available() and not _on_cooldown(f"{p.id}/{u}") for p in _instances() for pid2, u, _ in AUTO_CANDIDATES if pid2 == p.id):
            # skip very hot cooldown candidates when alternatives exist
            tried.add(model.id)
            continue
        tried.add(model.id)
        data = await try_one(provider, model)
        if data:
            return data, attempts
        await asyncio.sleep(0.15)

    detail = " | ".join(f"{a['provider']}/{a['model'].split('/',1)[-1]}: {a.get('error','')[:140]}" for a in attempts[-6:]) or "Sin proveedores disponibles"
    raise ProviderError(
        f"Todos los proveedores/cuentas disponibles fallaron o están limitados en este intento. {detail}. "
        "Sugerencia: usa model:\"auto\" con peticiones espaciadas/caché, o agrega más cuentas gratuitas en .env. "
        "Limitación real: los tiers gratuitos tienen cuotas/rate limits/créditos.",
        status=502, provider="gateway",
    )


async def stream_with_fallback(payload: dict[str, Any]) -> AsyncIterator[bytes]:
    requested = (payload.get("model") or "auto").strip() or "auto"
    candidates: list[tuple[Any, ModelInfo]] = []
    tried: set[str] = set()
    if requested != "auto":
        try:
            p, m = await resolve_model(requested)
            candidates.append((p, m)); tried.add(m.id)
        except Exception:
            pass
    candidates.extend(_build_auto_plan(exclude=tried, max_items=12))
    errors = []
    for p, m in candidates[:10]:
        if _cooldown_left(m.id) > 15:
            continue
        t0 = time.time()
        try:
            async for chunk in p.stream_chat(payload, m):
                yield chunk
            _record(p.id, ok=True, ms=int((time.time() - t0) * 1000))
            return
        except Exception as e:
            err = str(e)[:220]
            errors.append(f"{m.id}: {err}")
            _mark_cooldown(m.id, _cooldown_for(e))
            _record(p.id, ok=False, ms=int((time.time() - t0) * 1000), error=err)
            continue
    raise ProviderError("Streaming fallback agotado: " + " | ".join(errors[-4:]), status=502, provider="gateway")
