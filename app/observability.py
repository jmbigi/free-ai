from __future__ import annotations
import threading
import time
import uuid
from collections import deque, defaultdict
from dataclasses import dataclass, field
from typing import Any

_START = time.time()


@dataclass
class ConnectionInfo:
    """Track individual connection info."""
    id: str
    path: str
    method: str
    start_time: float
    client_ip: str
    user_agent: str = ""
    status: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0


@dataclass
class Metrics:
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    requests_total: int = 0
    requests_ok: int = 0
    requests_error: int = 0
    by_path: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    by_method: dict[str, int] = field(default_factory=dict)
    latencies_ms: deque[int] = field(default_factory=lambda: deque(maxlen=5000))
    last_errors: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=50))
    
    # Connection tracking
    active_connections: dict[str, ConnectionInfo] = field(default_factory=dict)
    connections_total: int = 0
    connections_current: int = 0
    connections_peak: int = 0
    connection_durations_ms: deque[int] = field(default_factory=lambda: deque(maxlen=2000))
    by_client_ip: dict[str, int] = field(default_factory=dict)
    
    # Provider stats (from router)
    provider_stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    def observe(self, *, path: str, status: int, ms: int, request_id: str = "", error: str = "", method: str = "GET", client_ip: str = "") -> None:
        key = path.split('?')[0]
        if key.startswith('/v1/') and key.count('/') > 2:
            pass
        with self.lock:
            self.requests_total += 1
            if 200 <= status < 400:
                self.requests_ok += 1
            else:
                self.requests_error += 1
            self.by_path[key] = self.by_path.get(key, 0) + 1
            self.by_method[method] = self.by_method.get(method, 0) + 1
            sk = str(status)
            self.by_status[sk] = self.by_status.get(sk, 0) + 1
            self.latencies_ms.append(max(0, int(ms)))
            if client_ip:
                self.by_client_ip[client_ip] = self.by_client_ip.get(client_ip, 0) + 1
            if error and status >= 400:
                self.last_errors.append({
                    'ts': int(time.time()), 'request_id': request_id, 'status': status,
                    'path': key, 'error': error[:300],
                })

    def connection_start(self, path: str, method: str, client_ip: str, user_agent: str = "") -> str:
        """Register new connection, return connection ID."""
        conn_id = uuid.uuid4().hex[:16]
        now = time.time()
        with self.lock:
            self.active_connections[conn_id] = ConnectionInfo(
                id=conn_id, path=path, method=method, start_time=now,
                client_ip=client_ip, user_agent=user_agent
            )
            self.connections_total += 1
            self.connections_current += 1
            if self.connections_current > self.connections_peak:
                self.connections_peak = self.connections_current
            if client_ip:
                self.by_client_ip[client_ip] = self.by_client_ip.get(client_ip, 0) + 1
        return conn_id

    def connection_end(self, conn_id: str, status: int = 0, bytes_sent: int = 0, bytes_received: int = 0) -> None:
        """Register connection end, record duration."""
        now = time.time()
        with self.lock:
            conn = self.active_connections.pop(conn_id, None)
            if conn:
                duration_ms = int((now - conn.start_time) * 1000)
                self.connection_durations_ms.append(max(0, duration_ms))
                self.connections_current = max(0, self.connections_current - 1)
            else:
                # connection not tracked, still record
                pass

    def update_provider_stats(self, provider_id: str, stats: dict[str, Any]) -> None:
        """Update provider statistics from router."""
        with self.lock:
            self.provider_stats[provider_id] = {**self.provider_stats.get(provider_id, {}), **stats}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            lats = list(self.latencies_ms)
            avg = int(sum(lats) / len(lats)) if lats else 0
            p50 = p95 = p99 = 0
            if lats:
                s = sorted(lats)
                n = len(s)
                p50 = s[min(n - 1, int(n * 0.50))]
                p95 = s[min(n - 1, int(n * 0.95))]
                p99 = s[min(n - 1, int(n * 0.99))]
            
            conn_durs = list(self.connection_durations_ms)
            avg_conn = int(sum(conn_durs) / len(conn_durs)) if conn_durs else 0
            p95_conn = 0
            if conn_durs:
                s = sorted(conn_durs)
                p95_conn = s[min(len(s) - 1, int(len(s) * 0.95))]

            return {
                'uptime_s': int(time.time() - _START),
                'requests': {
                    'total': self.requests_total,
                    'ok': self.requests_ok,
                    'error': self.requests_error,
                    'by_method': dict(sorted(self.by_method.items(), key=lambda kv: -kv[1])),
                },
                'latency_ms': {
                    'avg': avg, 'p50': p50, 'p95': p95, 'p99': p99, 'samples': len(lats)
                },
                'connections': {
                    'total': self.connections_total,
                    'current': self.connections_current,
                    'peak': self.connections_peak,
                    'avg_duration_ms': avg_conn,
                    'p95_duration_ms': p95_conn,
                    'samples': len(conn_durs),
                },
                'by_status': dict(sorted(self.by_status.items())),
                'top_paths': dict(sorted(self.by_path.items(), key=lambda kv: -kv[1])[:30]),
                'top_clients': dict(sorted(self.by_client_ip.items(), key=lambda kv: -kv[1])[:20]),
                'last_errors': list(self.last_errors)[-10:],
                'providers': self.provider_stats,
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

