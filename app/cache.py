from __future__ import annotations
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any

from .config import settings

@dataclass
class CacheEntry:
    value: dict[str, Any]
    expires_at: float
    created_at: float
    hits: int = 0

class TTLCache:
    def __init__(self, max_items: int = 512):
        self.max_items = max(16, int(max_items))
        self._items: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()
        self.stats = {"hits": 0, "misses": 0, "sets": 0, "evictions": 0, "expirations": 0}

    def _now(self) -> float:
        return time.time()

    def _purge_expired(self) -> None:
        now = self._now()
        dead = [k for k, v in self._items.items() if v.expires_at <= now]
        for k in dead:
            self._items.pop(k, None)
            self.stats["expirations"] += 1

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge_expired()
            item = self._items.get(key)
            if not item:
                self.stats["misses"] += 1
                return None
            item.hits += 1
            self.stats["hits"] += 1
            self._items.move_to_end(key)
            # return copy-ish
            return json.loads(json.dumps(item.value))

    def set(self, key: str, value: dict[str, Any], ttl: int) -> None:
        with self._lock:
            self._purge_expired()
            if key in self._items:
                self._items.pop(key, None)
            while len(self._items) >= self.max_items:
                self._items.popitem(last=False)
                self.stats["evictions"] += 1
            now = self._now()
            self._items[key] = CacheEntry(value=json.loads(json.dumps(value)), expires_at=now + max(1, int(ttl)), created_at=now)
            self.stats["sets"] += 1

    def clear(self) -> int:
        with self._lock:
            n = len(self._items)
            self._items.clear()
            return n

    def info(self) -> dict[str, Any]:
        with self._lock:
            self._purge_expired()
            return {
                "enabled": bool(getattr(settings, 'cache_enabled', True)),
                "items": len(self._items),
                "max_items": self.max_items,
                "ttl_seconds": int(getattr(settings, 'cache_ttl_seconds', 300)),
                **self.stats,
            }

response_cache = TTLCache(max_items=int(getattr(settings, 'cache_max_items', 512) or 512))


def _norm_content(content: Any) -> Any:
    if isinstance(content, list):
        return [{"type": x.get("type"), **({"text": str(x.get("text",""))} if x.get("type") == "text" else x)} if isinstance(x, dict) else str(x) for x in content]
    return content if isinstance(content, (str, int, float, bool)) or content is None else str(content)


def normalize_messages(messages: Any) -> list[dict[str, Any]]:
    out = []
    if not isinstance(messages, list):
        return out
    for m in messages:
        if not isinstance(m, dict):
            continue
        item = {"role": str(m.get("role", "user")), "content": _norm_content(m.get("content"))}
        if m.get("name"):
            item["name"] = str(m["name"])
        if m.get("tool_call_id"):
            item["tool_call_id"] = str(m["tool_call_id"])
        if m.get("tool_calls"):
            item["tool_calls"] = m.get("tool_calls")
        out.append(item)
    return out


def cache_key(payload: dict[str, Any]) -> str:
    relevant = {
        "v": 2,
        "model": payload.get("model") or "auto",
        "messages": normalize_messages(payload.get("messages")),
        "temperature": payload.get("temperature", 1),
        "top_p": payload.get("top_p"),
        "max_tokens": payload.get("max_tokens"),
        "tools": payload.get("tools"),
        "tool_choice": payload.get("tool_choice"),
        "response_format": payload.get("response_format"),
        "seed": payload.get("seed"),
        "stop": payload.get("stop"),
    }
    raw = json.dumps(relevant, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cacheable(payload: dict[str, Any]) -> bool:
    if not bool(getattr(settings, 'cache_enabled', True)):
        return False
    gw = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
    if payload.get("cache") is False or gw.get("cache") is False or payload.get("no_cache") is True:
        return False
    if bool(payload.get("stream")):
        return False
    temp = payload.get("temperature")
    try:
        # cache deterministic or default-like requests; allow explicit cache=true
        if payload.get("cache") is True or gw.get("cache") is True:
            return True
        if temp is None:
            return True
        return float(temp) <= 0.0001
    except Exception as e:
        from .logging import log as _log
        _log.warning("cacheable failed: %s", e)
        return False
