from __future__ import annotations
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

_START = time.time()


@dataclass
class Metrics:
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    requests_total: int = 0
    requests_ok: int = 0
    requests_error: int = 0
    by_path: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    latencies_ms: deque[int] = field(default_factory=lambda: deque(maxlen=2000))
    last_errors: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=30))

    def observe(self, *, path: str, status: int, ms: int, request_id: str = "", error: str = "") -> None:
        key = path.split('?')[0]
        # normalize dynamic noise minimally
        if key.startswith('/v1/') and key.count('/') > 2:
            pass
        with self.lock:
            self.requests_total += 1
            if 200 <= status < 400:
                self.requests_ok += 1
            else:
                self.requests_error += 1
            self.by_path[key] = self.by_path.get(key, 0) + 1
            sk = str(status)
            self.by_status[sk] = self.by_status.get(sk, 0) + 1
            self.latencies_ms.append(max(0, int(ms)))
            if error and status >= 400:
                self.last_errors.append({
                    'ts': int(time.time()), 'request_id': request_id, 'status': status,
                    'path': key, 'error': error[:300],
                })

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            lats = list(self.latencies_ms)
            avg = int(sum(lats) / len(lats)) if lats else 0
            p95 = 0
            if lats:
                s = sorted(lats)
                p95 = s[min(len(s) - 1, int(len(s) * 0.95))]
            return {
                'uptime_s': int(time.time() - _START),
                'requests_total': self.requests_total,
                'requests_ok': self.requests_ok,
                'requests_error': self.requests_error,
                'latency_ms': {'avg': avg, 'p95': p95, 'samples': len(lats)},
                'by_status': dict(sorted(self.by_status.items())),
                'top_paths': dict(sorted(self.by_path.items(), key=lambda kv: -kv[1])[:25]),
                'last_errors': list(self.last_errors)[-10:],
            }

    def record(self, name: str, value: int = 1, **extra: Any) -> None:
        """Record arbitrary named events (e.g. stream chunk counters) without request status."""
        with self.lock:
            key = f"event:{name}"
            self.by_path[key] = self.by_path.get(key, 0) + value
            for k, v in (extra or {}).items():
                self.by_status[f"{key}:{k}"] = self.by_status.get(f"{key}:{k}", 0) + v
            self.latencies_ms.append(0)

metrics = Metrics()

