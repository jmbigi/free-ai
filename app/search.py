from __future__ import annotations
import asyncio
import html
import json
import re
import time
import urllib.parse
from typing import Any
import httpx
from .config import settings

_UA = "Mozilla/5.0 (compatible; FreeAIGateway/2.2; +https://ia.forthtrade.com/help)"
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _cache_get(key: str, ttl: int = 120) -> dict[str, Any] | None:
    v = _CACHE.get(key)
    if not v: return None
    if time.time() - v[0] > ttl:
        _CACHE.pop(key, None); return None
    return v[1]


def _cache_set(key: str, value: dict[str, Any]) -> None:
    if len(_CACHE) > 300:
        for k in list(_CACHE.keys())[:100]: _CACHE.pop(k, None)
    _CACHE[key] = (time.time(), value)


def _clean(s: str) -> str:
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))
    return re.sub(r'\s+', ' ', s).strip()


async def _ddg(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    # DuckDuckGo HTML endpoint: free/no key, but rate-limited/anti-bot; best-effort fallback.
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    async with httpx.AsyncClient(timeout=httpx.Timeout(12, connect=5), headers={"User-Agent": _UA, "Accept": "text/html"}, follow_redirects=True) as c:
        r = await c.get(url)
    if r.status_code >= 400:
        raise RuntimeError(f"DDG HTTP {r.status_code}")
    text = r.text
    out = []
    # result links/snippets
    for m in re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>|<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S | re.I):
        href = m.group(1) or m.group(4) or ''
        title = _clean(m.group(2) or m.group(5) or '')
        snippet = _clean(m.group(3) or '')
        if 'uddg=' in href:
            try:
                href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get('uddg', [href])[0]
            except Exception:
                pass
        if href.startswith('//'): href = 'https:' + href
        if title and href.startswith('http'):
            out.append({"title": title, "url": href, "snippet": snippet, "source": "duckduckgo"})
        if len(out) >= max_results: break
    return out


async def _tavily(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    key = getattr(settings, 'tavily_api_key', '') or getattr(settings, 'TAVILY_API_KEY', None) or ''
    if not key: raise RuntimeError("no key")
    body = {"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": False}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.tavily.com/search", json=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if r.status_code >= 400: raise RuntimeError(f"Tavily {r.status_code}: {r.text[:180]}")
    d = r.json()
    return [{"title": x.get("title",""), "url": x.get("url",""), "snippet": x.get("content",""), "source": "tavily"} for x in (d.get("results") or [])[:max_results]]


async def _searxng(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    base = getattr(settings, 'searxng_base_url', '') or getattr(settings, 'SEARXNG_BASE_URL', None) or ''
    if not base: raise RuntimeError("no base")
    url = base.rstrip('/') + '/search?' + urllib.parse.urlencode({"q": query, "format": "json"})
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.get(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    if r.status_code >= 400: raise RuntimeError(f"SearXNG {r.status_code}")
    d = r.json()
    return [{"title": x.get("title",""), "url": x.get("url",""), "snippet": x.get("content",""), "source": "searxng"} for x in (d.get("results") or [])[:max_results]]


async def _brave(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    key = getattr(settings, 'brave_search_api_key', '') or ''
    if not key: raise RuntimeError("no key")
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": max_results}, headers={"Accept": "application/json", "X-Subscription-Token": key})
    if r.status_code >= 400: raise RuntimeError(f"Brave {r.status_code}: {r.text[:180]}")
    d = r.json()
    items = ((d.get('web') or {}).get('results')) or []
    return [{"title": x.get("title",""), "url": x.get("url",""), "snippet": x.get("description",""), "source": "brave"} for x in items[:max_results]]


async def web_search(query: str, *, max_results: int = 5, provider: str = "auto") -> dict[str, Any]:
    query = (query or '').strip()
    if not query:
        return {"object": "search", "query": query, "results": [], "error": "missing query"}
    max_results = max(1, min(10, int(max_results or 5)))
    ck = f"{provider}|{max_results}|{query.lower()}"
    cached = _cache_get(ck)
    if cached:
        c = dict(cached); c["cached"] = True; return c
    attempts = []
    providers = []
    if provider and provider != 'auto':
        providers = [(provider, {'tavily':_tavily,'searxng':_searxng,'brave':_brave,'duckduckgo':_ddg,'ddg':_ddg}.get(provider))]
    else:
        providers = [('tavily',_tavily),('brave',_brave),('searxng',_searxng),('duckduckgo',_ddg)]
    for name, fn in providers:
        if not fn: continue
        try:
            results = await fn(query, max_results)
            attempts.append({"provider": name, "ok": True, "count": len(results)})
            if results:
                out = {"object":"search","query":query,"provider":name,"results":results,"attempts":attempts,"cached":False,
                       "limitations":"Resultados web de terceros; pueden estar incompletos/desactualizados. DuckDuckGo/scraping es best-effort y rate-limited; proveedores con API key dependen de cuota/términos."}
                _cache_set(ck, out); return out
        except Exception as e:
            attempts.append({"provider": name, "ok": False, "error": str(e)[:180]})
    out = {"object":"search","query":query,"provider":None,"results":[],"attempts":attempts,"cached":False,
           "error":"No se obtuvieron resultados. Configura TAVILY_API_KEY/BRAVE_SEARCH_API_KEY/SEARXNG_BASE_URL o reintenta; DDG puede estar rate-limited.",
           "limitations":"Búsqueda gratuita best-effort. Fuentes sujetas a cuota/rate limits/disponibilidad."}
    _cache_set(ck, out); return out
