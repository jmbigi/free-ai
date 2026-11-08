from __future__ import annotations
import time
from typing import Any

from .cache import response_cache
from .config import settings
from .observability import metrics
from .router import free_control_info, runtime_status

__version__ = "2.3.0"


async def telemetry() -> dict[str, Any]:
    """Telemetría agregada del gateway: métricas, runtime, caché y control FREE_ONLY.

    Útil para operadores de la comunidad: no expone claves upstream, cuerpos de
    petición ni datos personales. Solo contadores, latencias, cooldowns y estado.
    """
    snap = metrics.snapshot()
    rt = runtime_status()
    return {
        'object': 'telemetry',
        'time': int(time.time()),
        'version': __version__,
        'service': 'free-ai-gateway',
        'requests': snap,
        'runtime': rt,
        'cache': response_cache.info(),
        'free_control': free_control_info(),
        'limits': {
            'free_only': bool(getattr(settings, 'free_only', True)),
            'allow_paid_models': bool(getattr(settings, 'allow_paid_models', False)),
            'verify_free_tier': bool(getattr(settings, 'verify_free_tier', True)),
            'block_unknown_paid': bool(getattr(settings, 'block_unknown_paid', True)),
            'cache_enabled': bool(getattr(settings, 'cache_enabled', True)),
            'cache_ttl_seconds': int(getattr(settings, 'cache_ttl_seconds', 300)),
            'context_compress_enabled': bool(getattr(settings, 'context_compress_enabled', True)),
            'context_max_chars': int(getattr(settings, 'context_max_chars', 120000)),
            'context_keep_last_messages': int(getattr(settings, 'context_keep_last_messages', 12)),
            'context_message_max_chars': int(getattr(settings, 'context_message_max_chars', 12000)),
            'context_summary_max_chars': int(getattr(settings, 'context_summary_max_chars', 4000)),
            'request_timeout': int(getattr(settings, 'request_timeout', 45)),
        },
    }


async def telemetry_summary() -> dict[str, Any]:
    """Lightweight telemetry summary for health checks."""
    return {
        'object': 'telemetry.summary',
        'time': int(time.time()),
        'version': __version__,
        'service': 'free-ai-gateway',
        'uptime_s': int(time.time() - __import__('time').time()) if False else None,
        'requests_total': metrics.snapshot().get('requests_total', 0),
        'requests_ok': metrics.snapshot().get('requests_ok', 0),
        'requests_error': metrics.snapshot().get('requests_error', 0),
        'latency_ms': metrics.snapshot().get('latency_ms', {}),
    }
