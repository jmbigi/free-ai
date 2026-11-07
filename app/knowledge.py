from __future__ import annotations
import json
import time
import hashlib
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[1] / 'data'
KB_FILE = BASE / 'knowledge.json'
MAX_ITEMS = 2000


def _ensure() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    if not KB_FILE.exists():
        KB_FILE.write_text('{"items":[],"updated_at":0}', encoding='utf-8')


def _load() -> dict[str, Any]:
    _ensure()
    try:
        return json.loads(KB_FILE.read_text(encoding='utf-8') or '{}')
    except Exception:
        return {"items": [], "updated_at": 0}


def _save(data: dict[str, Any]) -> None:
    _ensure()
    data['updated_at'] = int(time.time())
    data['items'] = (data.get('items') or [])[-MAX_ITEMS:]
    tmp = KB_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(KB_FILE)


def add_source(*, title: str, url: str = '', content: str = '', tags: list[str] | None = None, source: str = 'manual', meta: dict[str, Any] | None = None) -> dict[str, Any]:
    data = _load()
    item = {
        'id': hashlib.sha1(f"{url}\n{title}\n{content[:500]}".encode('utf-8','ignore')).hexdigest()[:16],
        'title': (title or '')[:300], 'url': (url or '')[:1000], 'content': (content or '')[:8000],
        'tags': [str(t)[:50] for t in (tags or [])[:20]], 'source': source[:50], 'meta': meta or {}, 'ts': int(time.time()),
    }
    items = data.get('items') or []
    items = [x for x in items if x.get('id') != item['id']]
    items.append(item)
    data['items'] = items
    _save(data)
    return item


def query(q: str, *, limit: int = 5) -> dict[str, Any]:
    q = (q or '').strip().lower()
    terms = [t for t in re_split_terms(q) if t]
    data = _load()
    scored = []
    for it in data.get('items') or []:
        hay = ' '.join([str(it.get('title','')), str(it.get('url','')), str(it.get('content','')), ' '.join(it.get('tags') or [])]).lower()
        score = sum(3 for t in terms if t in str(it.get('title','')).lower()) + sum(1 for t in terms if t in hay)
        if score > 0:
            scored.append((score, it))
    scored.sort(key=lambda x: (-x[0], -int(x[1].get('ts',0))))
    results = [it for _, it in scored[:max(1,min(20,int(limit or 5)))]]
    return {'object':'knowledge.search','query':q,'count':len(results),'results':results,'total_items':len(data.get('items') or [])}


def re_split_terms(q: str) -> list[str]:
    import re
    return [x for x in re.split(r'[^a-z0-9áéíóúñü\-_.:/]+', q.lower()) if len(x) >= 2]


def stats() -> dict[str, Any]:
    data = _load(); items = data.get('items') or []
    return {'object':'knowledge.stats','items':len(items),'updated_at':data.get('updated_at'),'file':str(KB_FILE),'max_items':MAX_ITEMS}
