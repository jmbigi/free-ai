from __future__ import annotations
import asyncio
import time
from typing import Any, AsyncIterator
from .providers.pollinations import PollinationsProvider
from .providers.configured import (
    LLM7Provider,
    GroqProvider, OpenRouterProvider, NvidiaProvider, MistralProvider,
    SambaNovaProvider, CerebrasProvider, HuggingFaceProvider, TogetherProvider, CohereProvider,
    DeepSeekProvider, MoonshotProvider, OpenCodeProvider, LLM7Provider, GenericOpenAIProvider,
)
from .providers.gemini import GeminiProvider
from .providers.cloudflare import CloudflareProvider
from .providers.base import ModelInfo, ProviderError
from .config import settings
from .tool_support import has_tools, inject_tool_prompt, maybe_synthesize_tool_calls

# mid -> unix cooldown-until
_COOLDOWN: dict[str, float] = {}
# provider_id -> {ok,fail,last_ok,last_fail,last_error,latency_ms,ema_ms}
_STATS: dict[str, dict[str, Any]] = {}
# singleton instances + catalog cache (efficiency)
_INSTANCES: list[Any] | None = None
_CATALOG_CACHE: tuple[float, list[dict[str, Any]], list[dict[str, Any]]] | None = None
_CATALOG_LOCK = asyncio.Lock()
_CATALOG_TTL = 45.0


def _instances():
    global _INSTANCES
    if _INSTANCES is None:
        _INSTANCES = [
            PollinationsProvider(),
            OpenRouterProvider(), GroqProvider(), NvidiaProvider(), GeminiProvider(), CloudflareProvider(),
            MistralProvider(), SambaNovaProvider(), CerebrasProvider(), HuggingFaceProvider(),
            TogetherProvider(), CohereProvider(), DeepSeekProvider(), MoonshotProvider(), OpenCodeProvider(), LLM7Provider(), GenericOpenAIProvider(),
        ]
    return _INSTANCES

# Ordered fallback candidates. Only active/configured providers are used (except pollinations).
# Prefer anonymous/free-tier paths that are empirically available; keep direct :free model IDs as hints
# but some may return 404 depending on OpenRouter free policy/capacity.
AUTO_CANDIDATES = [
    ("pollinations", "openai-fast", "Pollinations anónimo"),
    ("pollinations", "openai", "Pollinations anónimo"),
    ("openrouter", "openrouter/free", "OpenRouter router free"),
    ("openrouter", "meta-llama/llama-3.3-70b-instruct:free", "OpenRouter :free"),
    ("openrouter", "google/gemma-4-31b-it:free", "OpenRouter :free"),
    ("openrouter", "qwen/qwen3-coder:free", "OpenRouter :free"),
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
    ("openrouter", "google/gemma-3-27b-it:free", "OpenRouter :free"),
    ("openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "OpenRouter :free"),
    ("openrouter", "liquid/lfm-2.5-2.6b:free", "OpenRouter :free"),
    ("llm7", "default", "LLM7 key-optional (best-effort)"),
]


def _stat(pid: str) -> dict[str, Any]:
    return _STATS.setdefault(pid, {"ok": 0, "fail": 0, "last_ok": None, "last_fail": None, "last_error": "", "latency_ms": None, "ema_ms": None})


def _record(pid: str, *, ok: bool, ms: int | None = None, error: str = ""):
    s = _stat(pid)
    s["ok" if ok else "fail"] += 1
    s["last_" + ("ok" if ok else "fail")] = int(time.time())
    if ms is not None:
        s["latency_ms"] = ms
        prev = s.get("ema_ms")
        s["ema_ms"] = int(ms if prev is None else (prev * 0.7 + ms * 0.3))
    if error:
        s["last_error"] = error[:300]


def runtime_status() -> dict[str, Any]:
    now = time.time()
    cds = {k: round(v - now, 1) for k, v in _COOLDOWN.items() if v > now}
    cache_age = round(now - _CATALOG_CACHE[0], 1) if _CATALOG_CACHE else None
    return {"cooldowns": cds, "stats": _STATS, "auto_candidates": len(AUTO_CANDIDATES), "free_control": _free_control_info(), "catalog_cache_age_s": cache_age, "catalog_ttl_s": _CATALOG_TTL}


async def catalog(*, refresh: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    global _CATALOG_CACHE
    now = time.time()
    if not refresh and _CATALOG_CACHE and (now - _CATALOG_CACHE[0]) < _CATALOG_TTL:
        return _CATALOG_CACHE[1], _CATALOG_CACHE[2]
    async with _CATALOG_LOCK:
        now = time.time()
        if not refresh and _CATALOG_CACHE and (now - _CATALOG_CACHE[0]) < _CATALOG_TTL:
            return _CATALOG_CACHE[1], _CATALOG_CACHE[2]
        models: list[ModelInfo] = []
        providers = []
        async def one(p):
            active = p.available()
            st = dict(_stat(p.id))
            try:
                listed = await asyncio.wait_for(p.list_models(), timeout=12)
            except Exception:
                listed = []
            return ({"id": p.id, "label": p.label, "active": active, "always_on": p.id == "pollinations", "stats": st}, listed, active or p.id == "pollinations")
        results = await asyncio.gather(*(one(p) for p in _instances()), return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            info, listed, include = r
            providers.append(info)
            if include:
                for m in listed:
                    if not any(x.id == m.id for x in models):
                        models.append(m)
        auto = ModelInfo(
            id="auto", provider="gateway", owned_by="gateway", upstream_model="auto",
            capabilities=["chat", "fallback", "retry", "cache-aware", "smart-routing"],
            note="Fallback automático eficiente con reintentos/cooldowns, selección inteligente por salud/latencia y control FREE_ONLY. No garantiza inferencia ilimitada: tiers gratuitos tienen cuotas/rate limits.",
        )
        out = (providers, [auto.__dict__] + [m.__dict__ for m in models])
        _CATALOG_CACHE = (time.time(), out[0], out[1])
        return out


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


def _is_free_model(model: ModelInfo | dict[str, Any]) -> bool:
    d = model.__dict__ if isinstance(model, ModelInfo) else (model if isinstance(model, dict) else {})
    mid = str(d.get('id') or '').lower()
    up = str(d.get('upstream_model') or '').lower()
    provider = str(d.get('provider') or '').lower()
    if provider == 'pollinations':
        return True
    if ':free' in mid or ':free' in up or mid.endswith('/free') or up == 'free' or 'openrouter/free' in mid:
        return True
    if 'free' in mid.split('/')[-1] and provider == 'openrouter':
        return True
    if provider == 'opencode' and not getattr(settings, 'opencode_api_key', ''):
        return True
    if getattr(settings, 'free_only', True) and not getattr(settings, 'allow_paid_models', False):
        return False
    return bool(d.get('free', False))


def _free_control_info() -> dict[str, Any]:
    return {
        'free_only': bool(getattr(settings, 'free_only', True)),
        'allow_paid_models': bool(getattr(settings, 'allow_paid_models', False)),
        'verify_free_tier': bool(getattr(settings, 'verify_free_tier', True)),
        'block_unknown_paid': bool(getattr(settings, 'block_unknown_paid', True)),
        'policy': 'Solo enruta a fuentes gratuitas/anónimas o candidatos free-tier explícitos (:free, Pollinations). Proveedores con API key propia pueden tener créditos/cuotas; no se garantiza gratuidad ilimitada upstream.',
        'limitation': 'No existe verificación criptográfica universal de que una cuenta upstream sea 100% gratuita; el gateway aplica control por política, allowlist free-tier y metadatos.',
    }


def free_control_info() -> dict[str, Any]:
    return _free_control_info()


def _retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    status = getattr(exc, 'status', None)
    if status in (401, 403, 404):
        return any(s in msg for s in ['quota', 'rate limit', 'free limit', 'credit', 'insufficient', 'provider', 'temporar'])
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
    if 'pollinations' in msg and ('45 seconds' in msg or 'free limit' in msg or 'every 45' in msg or 'rate limit' in msg):
        return 46.0
    if 'pollinations' in msg and status in (500, 502, 503, 504):
        return 4.0
    if status == 402 or 'insufficient' in msg or 'credit' in msg or 'balance' in msg or 'budget' in msg:
        return 120.0
    if status == 429 or '429' in msg or 'rate limit' in msg or 'quota' in msg or 'free limit' in msg:
        return 300.0 if ('per-day' in msg or 'daily' in msg) else 20.0
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
    # Fast default for interactive clients; explicit max_retries allows deeper fallback.
    return 4


def _build_auto_plan(*, exclude: set[str], max_items: int) -> list[tuple[Any, ModelInfo]]:
    scored = []
    for idx, (pid, upstream, label) in enumerate(AUTO_CANDIDATES):
        p = get_provider(pid)
        if not p or not (p.available() or pid == "pollinations"):
            continue
        mid = f"{pid}/{upstream}"
        if mid in exclude:
            continue
        m = ModelInfo(id=mid, provider=pid, owned_by=pid, upstream_model=upstream, capabilities=["chat"], note=label, free=_is_free_model({'id': mid, 'provider': pid, 'upstream_model': upstream}))
        if getattr(settings, 'free_only', True) and getattr(settings, 'block_unknown_paid', True) and not _is_free_model(m):
            continue
        left = _cooldown_left(mid)
        # keep pollinations eligible through short transient cooldowns; skip long/hard cooldowns
        if left > 45:
            continue
        if left > 10 and pid != 'pollinations':
            continue
        st = _stat(pid)
        ema = st.get('ema_ms') or 5000
        fail_penalty = min(st['fail'], 20) * 2.0
        fast_bonus = 12.0 if mid == 'pollinations/openai-fast' and left <= 0 else 0.0
        if mid.startswith('pollinations/') and left <= 0:
            fast_bonus = max(fast_bonus, 6.0)
        if left > 0:
            fast_bonus -= min(left, 8) * 0.8
        health = (st['ok'] * 2.0) - fail_penalty - (ema / 3000.0) + fast_bonus
        score = (1 if left > 3 else 0, left, -health, idx)
        scored.append((score, p, m))
    scored.sort(key=lambda x: x[0])
    return [(p, m) for _, p, m in scored[:max_items]]


async def execute_with_fallback(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    requested = (payload.get("model") or "auto").strip() or "auto"
    max_attempts = _clamp_attempts(payload)
    tried: set[str] = set()

    async def try_one(provider, model) -> dict[str, Any] | None:
        t0 = time.time()
        try:
            send = inject_tool_prompt(payload) if has_tools(payload) else payload
            data = await provider.chat(send, model)
            data = maybe_synthesize_tool_calls(data, payload)
            ms = int((time.time() - t0) * 1000)
            _record(provider.id, ok=True, ms=ms)
            attempts.append({"provider": provider.id, "model": model.id, "ok": True, "ms": ms})
            data.setdefault("gateway", {})
            data["gateway"]["attempts"] = attempts
            data["gateway"]["fallback_used"] = requested != model.id and (requested != 'auto' or len(attempts) > 1)
            data["gateway"]["selected"] = model.id
            data["gateway"]["max_attempts"] = max_attempts
            data["requested_model"] = requested
            data["gateway"]["free_control"] = _free_control_info()
            data["gateway"]["selected_is_free_tier"] = _is_free_model(model)
            return data
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            err = str(e)[:320]
            _record(provider.id, ok=False, ms=ms, error=err)
            _mark_cooldown(model.id, _cooldown_for(e))
            attempts.append({"provider": provider.id, "model": model.id, "ok": False, "ms": ms, "error": err, "retryable": _retryable(e)})
            return None

    def _raise_final(status: int = 502):
        detail = " | ".join(f"{a['provider']}/{a['model'].split('/',1)[-1]}: {a.get('error','')[:140]}" for a in attempts[-8:]) or "Sin proveedores disponibles"
        err = ProviderError(
            f"Todos los proveedores/cuentas disponibles fallaron o están limitados en este intento ({len(attempts)} intento(s), max={max_attempts}). {detail}. "
            "Sugerencia: usa model:\"auto\" con caché, espacia peticiones (Pollinations anónimo ~45s/IP), o agrega más cuentas/candidatos free-tier en .env. "
            "Limitación real: los tiers gratuitos tienen cuotas/rate limits/créditos/capacidad variable; no es inferencia ilimitada garantizada.",
            status=status, provider="gateway",
        )
        err.attempts = attempts  # type: ignore[attr-defined]
        raise err

    if requested != "auto":
        provider, model = await resolve_model(requested)
        if getattr(settings, 'free_only', True) and getattr(settings, 'block_unknown_paid', True) and not _is_free_model(model):
            raise ProviderError(
                f"Modelo bloqueado por política FREE_ONLY: {model.id}. Usa un modelo :free/anónimo o configura FREE_ONLY=0/ALLOW_PAID_MODELS=1 bajo tu responsabilidad.",
                status=403, provider="gateway",
            )
        tried.add(model.id)
        data = await try_one(provider, model)
        if data:
            return data, attempts
        last = attempts[-1] if attempts else {}
        if not last.get("retryable", True):
            detail = last.get("error") or "Solicitud rechazada por el proveedor"
            err = ProviderError(f"{provider.id}/{model.upstream_model}: {detail}", status=getattr(provider, 'last_status', 502) or 502, provider=provider.id)
            err.attempts = attempts  # type: ignore[attr-defined]
            raise err

    # Build plan and attempt across providers; keep latency bounded for auto.
    deadline = time.time() + max(8, min(45, int(getattr(settings, 'request_timeout', 45) or 45)))
    while len(attempts) < max_attempts and time.time() < deadline:
        plan = _build_auto_plan(exclude=tried, max_items=max_attempts * 2)
        if not plan:
            viable = []
            for pid, upstream, label in AUTO_CANDIDATES:
                p = get_provider(pid)
                if not p or not (p.available() or pid == "pollinations"): continue
                mid = f"{pid}/{upstream}"; m = ModelInfo(id=mid, provider=pid, owned_by=pid, upstream_model=upstream, capabilities=["chat"], note=label)
                if getattr(settings,'free_only',True) and getattr(settings,'block_unknown_paid',True) and not _is_free_model(m): continue
                left = _cooldown_left(mid)
                if left <= 3 and mid not in tried:
                    viable.append((mid, left, p, m))
            viable.sort(key=lambda x: x[1])
            if viable and time.time() + viable[0][1] < deadline and len(attempts) < max_attempts:
                wait = min(3.0, viable[0][1] + 0.05)
                attempts.append({"provider":"gateway","model":"wait","ok":False,"ms":int(wait*1000),"error":f"Esperando cooldown {wait:.1f}s para {viable[0][0]}","retryable":True})
                await asyncio.sleep(wait)
                tried.discard(viable[0][0])
                plan = _build_auto_plan(exclude=tried, max_items=max_attempts)
            if not plan:
                break
        made = False
        for provider, model in plan:
            if len(attempts) >= max_attempts or time.time() >= deadline:
                break
            if _cooldown_left(model.id) > 3:
                tried.add(model.id); continue
            tried.add(model.id); made = True
            data = await try_one(provider, model)
            if data:
                return data, attempts
            if time.time() >= deadline:
                break
        if not made:
            break
    _raise_final()


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
    plan = _build_auto_plan(exclude=tried, max_items=max_attempts)
    # Force-include fast pollinations candidates when FREE_ONLY allows, unless explicitly excluded/blocked by long cooldown.
    if requested == 'auto':
        forced = []
        for pid, upstream, label in [('pollinations','openai-fast','Pollinations anónimo'),('pollinations','openai','Pollinations anónimo')]:
            mid=f'{pid}/{upstream}'
            if mid in tried or _cooldown_left(mid) > 45: continue
            pp=get_provider(pid)
            if not pp: continue
            mm=ModelInfo(id=mid,provider=pid,owned_by=pid,upstream_model=upstream,capabilities=['chat'],note=label,free=True)
            if not any(m.id==mid for _,m in plan): forced.append((pp,mm))
        if forced:
            plan = forced + [(p,m) for p,m in plan if not m.id.startswith('pollinations/')]
    candidates.extend(plan)
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
