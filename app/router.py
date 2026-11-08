from __future__ import annotations
import asyncio
import random
import time
from typing import Any, AsyncIterator
from .observability import metrics as _metrics_obs
from .logging import log as _log
from .providers.pollinations import PollinationsProvider
from .providers.configured import (
    LLM7Provider,
    GroqProvider, OpenRouterProvider, NvidiaProvider, MistralProvider,
    SambaNovaProvider, CerebrasProvider, HuggingFaceProvider, TogetherProvider, CohereProvider,
    DeepSeekProvider, MoonshotProvider, OpenCodeProvider, LLM7Provider, GenericOpenAIProvider,
    NCMProvider, OllamaLocalProvider, NCMLm1bProvider,
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
# Free-tier spacing: serialize upstream calls with a minimum start interval.
_RATE_LOCKS: dict[str, asyncio.Lock] = {}
_RATE_LAST: dict[str, float] = {}
# Provider-level circuit breaker: avoid cycling every model of a dead/limited provider.
# provider_id -> {failures, opened_until, opened_at, kind, last_error}
_BREAKERS: dict[str, dict[str, Any]] = {}
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
            OllamaLocalProvider(), NCMProvider(), NCMLm1bProvider(),
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
    ("local-ollama", settings.local_ollama_model, "Qwen3.5-9B local (Ollama)"),
    ("ncm", settings.ncm_local_model, "NCM local experimental (thinker-lite)"),
]


async def _throttle(provider_id: str, *, deadline: float | None = None) -> None:
    """Space anonymous free-tier calls without blocking past the request budget.

    If the required wait cannot fit in the remaining budget, fail fast with
    Retry-After instead of sleeping and then failing anyway.
    """
    interval = float(getattr(settings, "pollinations_min_interval", 46) or 0) if provider_id == "pollinations" else 0.0
    if interval <= 0:
        return
    lock = _RATE_LOCKS.setdefault(provider_id, asyncio.Lock())
    acquire_timeout = None
    if deadline is not None:
        # Another request may already be sleeping on this provider. Never queue
        # behind it for the whole budget: wait at most 2s, then fail over fast.
        acquire_timeout = min(2.0, max(0.05, deadline - time.time()))
    try:
        if acquire_timeout is not None:
            await asyncio.wait_for(lock.acquire(), timeout=acquire_timeout)
        else:
            await lock.acquire()
    except asyncio.TimeoutError:
        # asyncio.Lock.acquire() is cancellation-safe: if the wait timed out we
        # never own the lock, so releasing here would corrupt the other owner.
        raise ProviderError(
            f"{provider_id} free-tier throttle busy; request budget exhausted while waiting.",
            status=429, provider=provider_id, retry_after=interval,
        )
    try:
        wait = interval - (time.time() - _RATE_LAST.get(provider_id, 0.0))
        if wait <= 0:
            _RATE_LAST[provider_id] = time.time()
            return
        max_wait = float(getattr(settings, "free_tier_max_wait", 60) or 60)
        if deadline is not None:
            max_wait = min(max_wait, max(0.0, deadline - time.time() - 0.5))
        if wait > max_wait:
            raise ProviderError(
                f"{provider_id} free-tier spacing requires waiting {wait:.0f}s "
                f"(allowed {max_wait:.0f}s for this request); failing over instead of blocking.",
                status=429, provider=provider_id, retry_after=wait,
            )
        _log.info("free-tier throttle %s: waiting %.1fs", provider_id, wait)
        await asyncio.sleep(wait)
        _RATE_LAST[provider_id] = time.time()
    finally:
        lock.release()


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
    try:
        _metrics_obs.update_provider_stats(pid, {
            "ok": s.get("ok", 0), "fail": s.get("fail", 0),
            "last_ok": s.get("last_ok"), "last_fail": s.get("last_fail"),
            "last_error": s.get("last_error") or "",
            "latency_ms": s.get("latency_ms"), "ema_ms": s.get("ema_ms"),
        })
    except Exception as e:
        _log.warning("metrics.update_provider_stats(%s) failed: %s", pid, e)


def runtime_status() -> dict[str, Any]:
    now = time.time()
    cds = {k: round(v - now, 1) for k, v in _COOLDOWN.items() if v > now}
    breakers = {
        pid: {
            "seconds_left": round(max(0.0, b.get("opened_until", 0.0) - now), 1),
            "kind": b.get("kind", ""),
            "failures": b.get("failures", 0),
            "last_error": (b.get("last_error") or "")[:200],
        }
        for pid, b in _BREAKERS.items()
        if b.get("opened_until", 0.0) > now
    }
    cache_age = round(now - _CATALOG_CACHE[0], 1) if _CATALOG_CACHE else None
    return {"cooldowns": cds, "provider_breakers": breakers, "stats": _STATS,
            "auto_candidates": len(AUTO_CANDIDATES), "free_control": _free_control_info(),
            "catalog_cache_age_s": cache_age, "catalog_ttl_s": _CATALOG_TTL}


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
            except Exception as e:
                _log.warning("list_models(%s) failed: %s", p.id, str(e)[:180])
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
    if provider in ('ncm', 'local-ollama', 'ncm-lm1b'):
        # Self-hosted local models: no upstream API cost.
        return True
    if provider == 'llm7':
        # Key-optional anonymous endpoint; free/best-effort, quota/availability vary.
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


def is_free_model(model: ModelInfo | dict[str, Any]) -> bool:
    """Public policy check used by catalogs/status so listed free flags match routing."""
    return _is_free_model(model)


def _retryable(exc: Exception) -> bool:
    return _classify_failure(exc) != "terminal"


def _cooldown_for(exc: Exception) -> float:
    msg = str(exc).lower()
    status = getattr(exc, 'status', None)
    # honor Retry-After header for rate-limit backoff
    ra = getattr(exc, 'retry_after', None)
    if ra is not None:
        try:
            return max(1.0, float(ra))
        except (TypeError, ValueError) as e:
            _log.debug("invalid Retry-After value %r: %s", ra, e)
    if 'pollinations' in msg and ('45 seconds' in msg or 'free limit' in msg or 'every 45' in msg or 'rate limit' in msg):
        return 46.0
    if 'pollinations' in msg and status in (500, 502, 503, 504):
        return 4.0
    if 'unavailable for free' in msg or 'paid ver' in msg or 'no endpoints found' in msg:
        return 1800.0
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
    delay = max(0.5, float(seconds))
    if delay >= 2.0:
        # Jitter avoids synchronized retry waves when many requests fail together.
        delay *= 1.0 + random.uniform(0.0, 0.15)
    _COOLDOWN[mid] = max(_COOLDOWN.get(mid, 0), time.time() + delay)


def _breaker(pid: str) -> dict[str, Any]:
    return _BREAKERS.setdefault(pid, {
        "failures": 0, "opened_until": 0.0, "opened_at": 0.0,
        "kind": "", "last_error": "",
    })


def _breaker_open(pid: str) -> bool:
    return _breaker(pid).get("opened_until", 0.0) > time.time()


def _breaker_left(pid: str) -> float:
    return max(0.0, _breaker(pid).get("opened_until", 0.0) - time.time())


def _breaker_success(pid: str) -> None:
    b = _breaker(pid)
    b.update(failures=0, opened_until=0.0, opened_at=0.0, kind="", last_error="")


def _breaker_failure(pid: str, kind: str, exc: Exception) -> None:
    """Open the provider circuit on account/rate-limit faults or repeated transients."""
    if kind not in ("provider", "transient"):
        return
    b = _breaker(pid)
    b["failures"] = int(b.get("failures", 0)) + 1
    b["last_error"] = str(exc)[:300]
    b["kind"] = kind
    now = time.time()
    if kind == "provider":
        # 401/403 (bad key) and 402/429 (quota/rate limit) are provider-wide:
        # one failure is enough; retrying other models of the same account only burns quota.
        cooldown = float(getattr(exc, "retry_after", None) or _cooldown_for(exc))
        if getattr(exc, "status", None) in (401, 403):
            cooldown = max(cooldown, 300.0)
        cooldown = min(900.0, max(5.0, cooldown))
        b["opened_until"] = now + cooldown
        b["opened_at"] = now
        _log.warning("provider breaker OPEN %s: %.0fs (%s)", pid, cooldown, b["last_error"][:140])
        return
    threshold = max(1, int(getattr(settings, "provider_breaker_threshold", 3) or 3))
    if b["failures"] >= threshold:
        base = max(8.0, float(getattr(settings, "provider_breaker_cooldown", 60) or 60) / 4.0)
        exponent = min(4, b["failures"] - threshold)
        cooldown = min(120.0, base * (2 ** exponent))
        cooldown *= 1.0 + random.uniform(0.0, 0.2)
        b["opened_until"] = now + cooldown
        b["opened_at"] = now
        _log.warning("provider breaker OPEN %s: %.0fs after %d transient failures (%s)",
                     pid, cooldown, b["failures"], b["last_error"][:140])


def _classify_failure(exc: Exception) -> str:
    """Classify a failure to decide the exit strategy.

    terminal  -> the request itself is invalid; stop immediately.
    provider  -> key/quota/rate limit applies to the whole provider; skip all its models.
    model     -> only this model/route failed; another model may work.
    transient -> network/5xx/timeout; retry elsewhere and count toward the breaker.
    """
    status = getattr(exc, "status", None)
    msg = str(exc).lower()
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "transient"
    if status in (401, 403, 402, 429):
        return "provider"
    if status == 404:
        return "model" if ("model" in msg or "endpoint" not in msg) else "provider"
    if status in (400, 413, 422):
        if "model" in msg and any(s in msg for s in ("not found", "not supported", "does not exist", "unknown")):
            return "model"
        return "terminal"
    # Message heuristics can refine opaque 5xx/proxy errors.
    if any(s in msg for s in ("api key", "unauthorized", "forbidden", "invalid key", "authentication")):
        return "provider"
    if any(s in msg for s in ("quota", "rate limit", "free limit", "insufficient", "credit", "balance", "too many requests", "429", "402")):
        return "provider"
    if any(s in msg for s in ("model not found", "model_not_found", "not supported", "unknown model", "no endpoints")):
        return "model"
    if any(s in msg for s in ("invalid request", "bad request", "validation", "malformed")):
        return "terminal"
    if status in (408, 409, 425, 500, 502, 503, 504):
        return "transient"
    if any(s in msg for s in ("timeout", "timed out", "connection", "reset", "unavailable",
                              "overloaded", "temporar", "capacity", "503", "502", "504")):
        return "transient"
    return "transient"


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


def _build_auto_plan(*, exclude: set[str], max_items: int,
                     skip_providers: set[str] | None = None,
                     allowed_providers: set[str] | None = None) -> list[tuple[Any, ModelInfo]]:
    scored = []
    skip = skip_providers or set()
    for idx, (pid, upstream, label) in enumerate(AUTO_CANDIDATES):
        if pid in skip or _breaker_open(pid):
            continue
        if allowed_providers is not None and pid not in allowed_providers:
            continue
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
        # Local models are last-resort fallbacks: never let their latency or
        # success stats promote them above remote free-tier providers.
        local_last = 1 if pid in ("ncm", "local-ollama") else 0
        score = (local_last, 1 if left > 3 else 0, left, -health, idx)
        scored.append((score, p, m))
    scored.sort(key=lambda x: x[0])
    # Priority: one model per remote provider, then local NCM, then second
    # models of remote providers. This keeps NCM reachable within the default
    # attempt budget while still treating it as a last-resort route.
    local_ids = ("local-ollama", "ncm")
    remote = [(score, p, m) for score, p, m in scored if p.id not in local_ids]
    local = [(score, p, m) for score, p, m in scored if p.id in local_ids]
    out: list[tuple[Any, ModelInfo]] = []
    per_provider: dict[str, int] = {}
    seen_models: set[str] = set()

    def add(p: Any, m: ModelInfo) -> bool:
        if m.id in seen_models or len(out) >= max_items:
            return False
        out.append((p, m))
        seen_models.add(m.id)
        per_provider[p.id] = per_provider.get(p.id, 0) + 1
        return True

    reserve_local = 1 if local else 0
    for _, p, m in remote:
        if len(out) >= max_items - reserve_local:
            break
        if per_provider.get(p.id, 0) < 1:
            add(p, m)
    for _, p, m in local:
        add(p, m)
    for _, p, m in remote:
        if per_provider.get(p.id, 0) < 2:
            add(p, m)
    return out


def _wrap_terminal(exc: Exception, attempts: list[dict[str, Any]]) -> ProviderError:
    """Turn a request-level (non-retryable) failure into one honest gateway error."""
    status = int(getattr(exc, "status", 400) or 400)
    err = ProviderError(
        f"Solicitud rechazada como no reintentable ({status}): {str(exc)[:300]}. "
        "No se reintenta en otros proveedores: el mismo body fallaría y solo consumiría cuota/ciclos.",
        status=status if 400 <= status < 500 else 400, provider="gateway",
    )
    err.attempts = attempts  # type: ignore[attr-defined]
    return err


async def execute_with_fallback(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    requested = (payload.get("model") or "auto").strip() or "auto"
    max_attempts = _clamp_attempts(payload)
    budget = min(
        float(getattr(settings, 'request_budget', 45) or 45),
        float(getattr(settings, 'request_timeout', 45) or 45),
    )
    deadline = time.time() + max(5.0, budget)
    tried: set[str] = set()
    skipped_providers: set[str] = set()
    terminal: Exception | None = None
    calls = 0

    async def try_one(provider, model) -> dict[str, Any] | None:
        nonlocal terminal, calls
        if provider.id in skipped_providers:
            return None
        breaker_left = _breaker_left(provider.id)
        if breaker_left > 0:
            skipped_providers.add(provider.id)
            attempts.append({
                "provider": provider.id, "model": model.id, "ok": False, "ms": 0,
                "error": f"circuit breaker open ({breaker_left:.0f}s left)",
                "kind": "provider", "retryable": True, "skipped": True,
            })
            return None
        calls += 1
        t0 = time.time()
        try:
            await _throttle(provider.id, deadline=deadline)
            remaining = deadline - time.time()
            if remaining <= 0.25:
                raise ProviderError("request budget exhausted before provider call", status=504, provider=provider.id)
            send = inject_tool_prompt(payload) if has_tools(payload) else payload
            # Hard cap: a provider call can never outlive the request budget.
            data = await asyncio.wait_for(provider.chat(send, model), timeout=remaining)
            data = maybe_synthesize_tool_calls(data, payload)
            ms = int((time.time() - t0) * 1000)
            _record(provider.id, ok=True, ms=ms)
            _breaker_success(provider.id)
            attempts.append({"provider": provider.id, "model": model.id, "ok": True, "ms": ms})
            data.setdefault("gateway", {})
            data["gateway"]["attempts"] = attempts
            data["gateway"]["fallback_used"] = requested != model.id and (requested != 'auto' or calls > 1)
            data["gateway"]["selected"] = model.id
            data["gateway"]["max_attempts"] = max_attempts
            data["requested_model"] = requested
            data["gateway"]["free_control"] = _free_control_info()
            data["gateway"]["selected_is_free_tier"] = _is_free_model(model)
            return data
        except Exception as e:
            if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
                e = ProviderError(
                    f"provider call exceeded request budget ({max(0.0, deadline - time.time()):.1f}s left)",
                    status=504, provider=provider.id,
                )
            ms = int((time.time() - t0) * 1000)
            err = str(e)[:320]
            kind = _classify_failure(e)
            _record(provider.id, ok=False, ms=ms, error=err)
            _mark_cooldown(model.id, _cooldown_for(e))
            if kind == "provider":
                # One quota/auth failure is provider-wide: do not cycle its remaining models.
                skipped_providers.add(provider.id)
                _breaker_failure(provider.id, kind, e)
            elif kind == "transient":
                _breaker_failure(provider.id, kind, e)
            elif kind == "terminal":
                terminal = e
            attempts.append({
                "provider": provider.id, "model": model.id, "ok": False, "ms": ms,
                "error": err, "kind": kind, "retryable": kind != "terminal",
            })
            _log.warning(
                "%s/%s failed: kind=%s retryable=%s (ms=%d): %s",
                provider.id, model.id, kind, kind != "terminal", ms, err[:120],
            )
            if terminal is not None:
                raise _wrap_terminal(terminal, attempts)
            return None

    def _raise_final(status: int = 502):
        now = time.time()
        soonest: float | None = None
        for until in _COOLDOWN.values():
            left = until - now
            if left > 0:
                soonest = left if soonest is None else min(soonest, left)
        for b in _BREAKERS.values():
            left = b.get("opened_until", 0.0) - now
            if left > 0:
                soonest = left if soonest is None else min(soonest, left)
        detail = " | ".join(
            f"{a['provider']}/{a['model'].split('/', 1)[-1]}: {a.get('error', '')[:140]}"
            for a in attempts[-8:]
        ) or "Sin proveedores disponibles"
        retry_hint = f" Reintenta en ~{soonest:.0f}s." if soonest else ""
        err = ProviderError(
            f"Fallback agotado tras {calls} llamada(s) reales (max={max_attempts}); no quedan rutas viables sin bloquear. "
            f"{detail}.{retry_hint} "
            "Sugerencia: usa model:\"auto\" con caché, espacia peticiones (Pollinations anónimo ~45s/IP), o agrega más cuentas/candidatos free-tier en .env. "
            "Limitación real: los tiers gratuitos tienen cuotas/rate limits/créditos/capacidad variable; no es inferencia ilimitada garantizada.",
            status=status, provider="gateway",
        )
        if soonest:
            err.retry_after = soonest  # type: ignore[attr-defined]
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
        # A model-specific/provider-specific failure may still have a healthy fallback.

    # Build the plan once, then try at most one route per provider (two models max).
    gw_in = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
    allowed = set(gw_in["providers"]) if isinstance(gw_in.get("providers"), list) else None
    plan = _build_auto_plan(
        exclude=tried, max_items=max_attempts * 2,
        skip_providers=skipped_providers,
        allowed_providers=allowed,
    )
    for provider, model in plan:
        if calls >= max_attempts or time.time() >= deadline:
            break
        if provider.id in skipped_providers or _breaker_open(provider.id):
            skipped_providers.add(provider.id)
            continue
        if model.id in tried:
            continue
        tried.add(model.id)
        if _cooldown_left(model.id) > 0:
            # Never sleep inside a request; another route or a clear Retry-After is better.
            continue
        data = await try_one(provider, model)
        if data:
            return data, attempts
        if terminal is not None:
            raise _wrap_terminal(terminal, attempts)
    _raise_final()


async def stream_with_fallback(payload: dict[str, Any]) -> AsyncIterator[bytes]:
    requested = (payload.get("model") or "auto").strip() or "auto"
    candidates: list[tuple[Any, ModelInfo]] = []
    tried: set[str] = set()
    skipped_providers: set[str] = set()
    max_attempts = _clamp_attempts(payload)
    start_budget = max(2.0, min(
        float(getattr(settings, 'stream_start_budget', 12) or 12),
        float(getattr(settings, 'free_tier_max_wait', 60) or 60),
    ))
    if requested != "auto":
        try:
            p, m = await resolve_model(requested)
            candidates.append((p, m)); tried.add(m.id)
        except Exception as e:
            _log.warning("resolve_model(%s) failed: %s", requested, str(e)[:180])
    gw_in = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
    allowed = set(gw_in["providers"]) if isinstance(gw_in.get("providers"), list) else None
    plan = _build_auto_plan(exclude=tried, max_items=max_attempts,
                            skip_providers=skipped_providers,
                            allowed_providers=allowed)
    # Force-include fast pollinations candidates when FREE_ONLY allows, unless explicitly excluded/blocked by long cooldown.
    if requested == 'auto' and not _breaker_open('pollinations'):
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
    errors: list[str] = []
    calls = 0
    for p, m in candidates[:10]:
        if calls >= max_attempts:
            break
        if p.id in skipped_providers or _breaker_open(p.id):
            skipped_providers.add(p.id)
            continue
        if _cooldown_left(m.id) > 0:
            # Do not sleep on a cooling model; try another route immediately.
            continue
        calls += 1
        t0 = time.time()
        yielded = False
        try:
            # Bound the initial free-tier wait: fail over instead of blocking the stream.
            await _throttle(p.id, deadline=time.time() + start_budget)
            async for chunk in p.stream_chat(payload, m):
                yielded = True
                yield chunk
            _record(p.id, ok=True, ms=int((time.time() - t0) * 1000))
            _breaker_success(p.id)
            return
        except Exception as e:
            err = str(e)[:220]
            kind = _classify_failure(e)
            errors.append(f"{m.id} [{kind}]: {err}")
            _log.warning(
                "stream provider %s failed: kind=%s %s",
                m.id, kind, err[:120],
            )
            _mark_cooldown(m.id, _cooldown_for(e))
            _record(p.id, ok=False, ms=int((time.time() - t0) * 1000), error=err)
            if kind == "provider":
                skipped_providers.add(p.id)
                _breaker_failure(p.id, kind, e)
            elif kind == "transient":
                _breaker_failure(p.id, kind, e)
            if yielded:
                raise ProviderError(
                    f"Stream interrupted after partial output from {m.id}; not retrying to avoid mixed responses: {err}",
                    status=502, provider=p.id,
                ) from e
            if kind == "terminal":
                raise _wrap_terminal(e, [{"provider": p.id, "model": m.id, "ok": False,
                                           "error": err, "kind": kind}]) from e
            continue
    now = time.time()
    soonest: float | None = None
    for until in _COOLDOWN.values():
        left = until - now
        if left > 0:
            soonest = left if soonest is None else min(soonest, left)
    for b in _BREAKERS.values():
        left = b.get("opened_until", 0.0) - now
        if left > 0:
            soonest = left if soonest is None else min(soonest, left)
    hint = f" Reintenta en ~{soonest:.0f}s." if soonest else ""
    err = ProviderError(
        f"Streaming fallback agotado tras {calls} llamada(s); no se bloquea más. "
        + " | ".join(errors[-4:]) + hint,
        status=502, provider="gateway",
    )
    if soonest:
        err.retry_after = soonest  # type: ignore[attr-defined]
    raise err
