from __future__ import annotations
import copy
import json
import time
import traceback
import uuid
from typing import Any
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from .auth import require_api_key_flexible
from .cache import cache_key, cacheable, response_cache
from .config import settings
from .context import compress_messages
from .providers.base import ProviderError
from .router import catalog, execute_with_fallback, stream_with_fallback, runtime_status, free_control_info
from .observability import metrics
from .help_page import render_help_html, help_payload
from .tool_repair import repair_messages
from .search import web_search
from .knowledge import add_source as kb_add, query as kb_query, stats as kb_stats

app = FastAPI(
    title="Free AI Gateway",
    version="2.3.0",
    description=(
        "Gateway productivo OpenAI-compatible con una API key simple (.env API_KEY). "
        "Agrega y enruta a APIs remotas gratuitas/configuradas con fallback automático, "
        "caché de prompts/respuestas y compresión de contextos."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"], expose_headers=["*"],
)

REQUEST_ID_HEADER = "x-request-id"
MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB safety cap for JSON payloads


def _rid(request: Request) -> str:
    rid = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
    if rid and len(rid) <= 128:
        return rid
    return uuid.uuid4().hex


def _openai_error(message: str, *, type_: str = "gateway_error", code: Any = None, param: Any = None, request_id: str = "") -> dict[str, Any]:
    err = {"message": str(message)[:2000], "type": type_}
    if param is not None:
        err["param"] = param
    if code is not None:
        err["code"] = code
    if request_id:
        err["request_id"] = request_id
    return {"error": err}


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    rid = _rid(request)
    request.state.request_id = rid
    t0 = time.time()
    status = 500
    err_msg = ""
    conn_id = metrics.connection_start(
        path=request.url.path,
        method=request.method,
        client_ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent") or "",
    )
    try:
        # cheap body-size guard for mutating JSON endpoints
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
                status = 413
                return JSONResponse(status_code=413, content=_openai_error(f"Request body too large (max {MAX_BODY_BYTES} bytes)", type_="invalid_request_error", code=413, request_id=rid), headers={REQUEST_ID_HEADER: rid, "x-gateway-version": app.version})
        response = await call_next(request)
        status = response.status_code
        response.headers[REQUEST_ID_HEADER] = rid
        response.headers["x-gateway-version"] = app.version
        return response
    except Exception as e:
        err_msg = str(e)
        raise
    finally:
        ms = int((time.time() - t0) * 1000)
        metrics.connection_end(conn_id=conn_id, status=status)
        metrics.observe(
            path=request.url.path,
            status=status,
            ms=ms,
            request_id=rid,
            error=err_msg,
            method=request.method,
            client_ip=request.client.host if request.client else "",
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    rid = getattr(request.state, "request_id", "") or _rid(request)
    detail = exc.detail
    if isinstance(detail, dict) and "message" in detail:
        body = {"error": {**detail}}
        body["error"].setdefault("type", "gateway_error")
        body["error"].setdefault("code", exc.status_code)
        body["error"]["request_id"] = rid
    elif isinstance(detail, dict) and "error" in detail:
        body = detail
        if isinstance(body.get("error"), dict):
            body["error"]["request_id"] = rid
    else:
        body = _openai_error(detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False), code=exc.status_code, request_id=rid,
                             type_="authentication_error" if exc.status_code == 401 else "invalid_request_error" if exc.status_code < 500 else "gateway_error")
    return JSONResponse(status_code=exc.status_code, content=body, headers={REQUEST_ID_HEADER: rid, "x-gateway-version": app.version})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    rid = getattr(request.state, "request_id", "") or _rid(request)
    msg = "; ".join((e.get("msg") or str(e)) for e in exc.errors()[:5])[:800]
    return JSONResponse(status_code=422, content=_openai_error(msg or "Validation error", type_="invalid_request_error", code=422, request_id=rid), headers={REQUEST_ID_HEADER: rid})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", "") or _rid(request)
    # never leak stack traces/secrets
    metrics.observe(path=request.url.path, status=500, ms=0, request_id=rid, error=str(exc))
    return JSONResponse(status_code=500, content=_openai_error("Internal gateway error", type_="gateway_error", code=500, request_id=rid), headers={REQUEST_ID_HEADER: rid})

INDEX_HTML = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Free AI Gateway</title>
<style>
:root{--bg:#07111f;--p:#0f1a2f;--p2:#0b1426;--t:#edf4ff;--m:#9db2d3;--l:#203456;--a:#7c3aed;--b:#06b6d4;--ok:#22c55e;--bad:#ef4444}
*{box-sizing:border-box} body{margin:0;color:var(--t);font:15px/1.45 Inter,system-ui,Arial;background:radial-gradient(900px 500px at 0 -10%,#17305d,transparent),radial-gradient(700px 400px at 100% 0,#27135a,transparent),var(--bg)}
.w{max-width:1280px;margin:0 auto;padding:22px}.h{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:14px} h1{margin:0;font-size:30px}
.s{color:var(--m);max-width:980px;margin-top:6px}.g{display:grid;grid-template-columns:390px 1fr;gap:14px}@media(max-width:980px){.g{grid-template-columns:1fr}}
.c{background:linear-gradient(180deg,rgba(255,255,255,.04),rgba(255,255,255,.015));border:1px solid var(--l);border-radius:18px;padding:16px}
label{display:block;font-size:12px;color:var(--m);margin:10px 0 6px} input,select,textarea,button{width:100%;border:1px solid var(--l);background:var(--p2);color:var(--t);border-radius:12px;padding:11px 12px;font:inherit}
textarea{min-height:220px;resize:vertical} button{cursor:pointer;border:none;background:linear-gradient(135deg,var(--a),#2563eb);font-weight:700}
.r{display:flex;gap:8px}.r>*{flex:1} pre{margin:0;white-space:pre-wrap;word-break:break-word;background:#081120;border:1px solid var(--l);border-radius:12px;padding:12px;min-height:160px}
.pill{display:inline-flex;gap:6px;align-items:center;padding:5px 10px;border:1px solid var(--l);border-radius:999px;color:var(--m);font-size:12px;margin:3px 6px 0 0;background:rgba(255,255,255,.02)}
.dot{width:8px;height:8px;border-radius:50%;background:var(--bad)} .dot.on{background:var(--ok)} code{background:#081120;border:1px solid var(--l);padding:1px 6px;border-radius:6px}
.meta{color:var(--m);font-size:12px;margin-top:10px} a{color:#8bdcff;text-decoration:none}
</style></head><body><div class="w">
<div class="h"><div><h1>Free AI Gateway</h1><div class="s">Servicio productivo OpenAI-compatible con <b>una API key simple</b> (<code>API_KEY</code>). Agrega APIs remotas gratuitas/configuradas, usa <code>model:"auto"</code> con fallback, e incluye <b>caché de prompts/respuestas</b> y <b>compresión de contexto</b> para clientes como KiloCode/OpenCode/DeepSeek harness.</div></div>
<div><a class="pill" href="/docs" target="_blank">Swagger</a><a class="pill" href="/health" target="_blank">Health</a><a class="pill" href="/v1/cache" target="_blank">Cache</a></div></div>
<div class="g"><div class="c">
<label>API Key (gateway)</label><input id="key" type="password" placeholder="API_KEY del .env"/>
<label>Modelo</label><select id="model"><option value="auto">auto (fallback remoto)</option></select>
<div class="r"><div><label>temperature</label><input id="temp" type="number" step="0.1" value="0"/></div><div><label>max_tokens</label><input id="max_tokens" type="number" value="2048"/></div></div>
<div class="r" style="margin-top:10px"><button id="send">Enviar</button><button id="reload" style="background:#16233d;border:1px solid var(--l)">Refrescar</button></div>
<label>Proveedores/cuentas activos</label><div id="providers"></div>
<div class="meta">Base URLs: <code>/v1</code>, <code>/openai/v1</code>, <code>/api/v1</code>. Auth: <code>Authorization: Bearer</code>, <code>api-key</code>, <code>x-api-key</code>, <code>?key=</code>/<code>?api_key=</code>. Caché automática para peticiones determinísticas (<code>temperature=0</code>) o <code>cache:true</code>. Compresión automática al superar <code>CONTEXT_MAX_CHARS</code> o con <code>compress_context:true</code>.</div>
</div><div class="c"><label>Prompt</label><textarea id="prompt">Responde solo: OK</textarea><label>Respuesta</label><pre id="out">Listo.</pre></div></div></div>
<script>
const $=id=>document.getElementById(id);
async function api(path,opts={}){const key=$('key').value.trim();const h={'Content-Type':'application/json',...(opts.headers||{})}; if(key) h.Authorization='Bearer '+key; const r=await fetch(path,{...opts,headers:h}); const t=await r.text(); let d; try{d=JSON.parse(t)}catch{d=t} if(!r.ok) throw {status:r.status,data:d}; return d}
async function load(){ $('out').textContent='Cargando...'; try{ const m=await api('/v1/models'); const s=$('model'),cur=s.value; s.innerHTML='<option value="auto">auto (fallback remoto)</option>'; for(const it of (m.data||[]).filter(x=>x.id!=='auto')){const o=document.createElement('option'); o.value=it.id; o.textContent=it.id; s.appendChild(o)} if([...s.options].some(o=>o.value===cur)) s.value=cur; const p=$('providers'); p.innerHTML=''; for(const it of (m.providers||[])){const sp=document.createElement('span'); sp.className='pill'; sp.innerHTML=`<span class="dot ${it.active?'on':''}"></span>${it.id}`; p.appendChild(sp)} $('out').textContent='OK. Usa /v1 como base URL OpenAI-compatible. temperature=0 habilita caché por defecto.' }catch(e){$('out').textContent=JSON.stringify(e,null,2)} }
$('reload').onclick=load; $('send').onclick=async()=>{ $('out').textContent='Generando...'; try{ const d=await api('/v1/chat/completions',{method:'POST',body:JSON.stringify({model:$('model').value||'auto',messages:[{role:'user',content:$('prompt').value}],temperature:parseFloat($('temp').value||'0'),max_tokens:parseInt($('max_tokens').value||'2048',10),cache:true,compress_context:true})}); $('out').textContent=(d?.choices?.[0]?.message?.content||JSON.stringify(d,null,2))+`\n\n---\nprovider=${d.provider||'?'} model=${d.model||'?'} cache=${JSON.stringify(d.gateway?.cache||{})} context=${JSON.stringify(d.gateway?.context||d.gateway?.context_compressed||false)}` }catch(e){$('out').textContent=JSON.stringify(e,null,2)} }; load();
</script></body></html>"""

def _normalize_legacy_tools(body: dict[str, Any]) -> dict[str, Any]:
    # Legacy functions/function_call -> tools/tool_choice for broad compatibility.
    if 'tools' not in body and isinstance(body.get('functions'), list):
        tools = []
        for fn in body['functions']:
            if isinstance(fn, dict):
                tools.append({'type': 'function', 'function': fn})
        if tools:
            body['tools'] = tools
    if 'tool_choice' not in body and 'function_call' in body:
        fc = body.get('function_call')
        if isinstance(fc, dict) and fc.get('name'):
            body['tool_choice'] = {'type': 'function', 'function': {'name': fc['name']}}
        elif fc in ('auto', 'none', 'required'):
            body['tool_choice'] = fc
    # normalize assistant/tool message legacy fields
    msgs = body.get('messages')
    if isinstance(msgs, list):
        out = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            mm = dict(m)
            if mm.get('role') == 'function':
                mm['role'] = 'tool'
                if 'tool_call_id' not in mm and mm.get('name'):
                    mm['tool_call_id'] = f"call_legacy_{mm['name']}"
            if 'function_call' in mm and 'tool_calls' not in mm and isinstance(mm.get('function_call'), dict):
                fc = mm['function_call']
                mm['tool_calls'] = [{'id': f"call_legacy_{fc.get('name','fn')}", 'type': 'function', 'function': {'name': fc.get('name'), 'arguments': fc.get('arguments') or '{}'}}]
            out.append(mm)
        body['messages'] = out
    return body

def _normalize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=_openai_error("Body must be a JSON object", type_="invalid_request_error", code=400))
    body = dict(payload)
    body.setdefault("model", "auto")
    if "max_completion_tokens" in body and "max_tokens" not in body:
        body["max_tokens"] = body.get("max_completion_tokens")
    body.pop("max_completion_tokens", None)
    if "max_output_tokens" in body and "max_tokens" not in body:
        body["max_tokens"] = body.get("max_output_tokens")
    if "messages" not in body and "prompt" in body:
        prompt = body.get("prompt")
        if isinstance(prompt, list):
            prompt = "\n".join(str(x) for x in prompt)
        body["messages"] = [{"role": "user", "content": str(prompt)}]
        body.pop("prompt", None)
    if "input" in body and "messages" not in body:
        inp = body.get("input")
        if isinstance(inp, str):
            body["messages"] = [{"role": "user", "content": inp}]
            body.pop("input", None)
        elif isinstance(inp, list):
            msgs = []
            for item in inp:
                if isinstance(item, dict):
                    role = item.get("role") or "user"
                    c = item.get("content")
                    if c is None and item.get('type') == 'message':
                        c = item.get('text')
                    if isinstance(c, list):
                        parts = []
                        for x in c:
                            if isinstance(x, dict):
                                parts.append(str(x.get('text') or x.get('input_text') or x.get('output_text') or ''))
                            else:
                                parts.append(str(x))
                        c = "\n".join([p for p in parts if p])
                    if c is not None or item.get('tool_calls'):
                        msg = {"role": role, "content": c}
                        for k in ('tool_calls','tool_call_id','name','function_call'):
                            if k in item: msg[k] = item[k]
                        msgs.append(msg)
            if msgs:
                body["messages"] = msgs
                body.pop("input", None)
    body = _normalize_legacy_tools(body)
    if "messages" not in body:
        raise HTTPException(status_code=400, detail=_openai_error("Missing messages/prompt/input", type_="invalid_request_error", param="messages", code=400))
    body['messages'], repair = repair_messages(body['messages'])
    if repair.get('repaired') or repair.get('missing_tool_results'):
        body.setdefault('gateway', {})['tool_repair'] = repair
    return body



@app.get("/help", response_class=HTMLResponse)
@app.get("/connect", response_class=HTMLResponse)
@app.get("/v1/help/ui", response_class=HTMLResponse)
async def help_ui(request: Request):
    base = str(request.base_url).rstrip('/')
    # prefer configured public base for displayed examples
    public = settings.public_base_url
    return render_help_html(public)

@app.get("/help.json")
@app.get("/v1/help")
@app.get("/openai/v1/help")
async def help_json(request: Request):
    return help_payload(settings.public_base_url)


@app.get("/ping")
@app.get("/v1/ping")
async def ping():
    return {"ok": True, "service": "free-ai-gateway", "version": app.version, "ts": int(time.time())}
@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML

@app.get("/health")
@app.head("/health")
@app.get("/v1/health")
@app.get("/openai/v1/health")
async def health():
    # Fast path: avoid upstream model-list calls on every health probe.
    snap = metrics.snapshot()
    rt = runtime_status()
    providers = []
    for p in __import__('app.router', fromlist=['_instances'])._instances():
        st = rt.get('stats', {}).get(p.id, {})
        providers.append({"id": p.id, "label": p.label, "active": p.available(), "always_on": p.id == "pollinations", "stats": st})
    active = [p["id"] for p in providers if p.get("active")]
    return {
        "status": "ok",
        "time": int(time.time()),
        "version": app.version,
        "uptime_s": snap.get("uptime_s", 0),
        "service": "free-ai-gateway",
        "public_base_url": settings.public_base_url + "/v1",
        "active_providers": active,
        "providers": providers,
        "models_hint": "GET /v1/models (auth) para catálogo completo; recomendado model=\"auto\".",
        "cache": response_cache.info(),
        "metrics": {"requests_total": snap.get('requests_total'), "avg_latency_ms": snap.get('latency_ms',{}).get('avg'), "p95_latency_ms": snap.get('latency_ms',{}).get('p95')},
        "context_compression": {
            "enabled": bool(getattr(settings, 'context_compress_enabled', True)),
            "max_chars": int(getattr(settings, 'context_max_chars', 120000)),
            "keep_last_messages": int(getattr(settings, 'context_keep_last_messages', 12)),
            "message_max_chars": int(getattr(settings, 'context_message_max_chars', 12000)),
        },
        "auth": "Simple API key from .env (API_KEY or FT_AI_API_KEY). Authorization: Bearer <key>, api-key, x-api-key, or ?api_key=. Env cliente: FT_AI_API_KEY.",
        "help": {"html": settings.public_base_url + "/help", "json": settings.public_base_url + "/help.json"},
        "compatibility": {
            "base_urls": [settings.public_base_url + "/v1", "/v1", "/openai/v1", "/api/v1"],
            "chat": ["POST /v1/chat/completions"],
            "responses": ["POST /v1/responses"],
            "models": ["GET /v1/models"],
            "observability": ["GET/POST /readyz", "GET/POST /v1/metrics", "GET/POST /v1/audit", "GET/POST /v1/status", "GET/POST /v1/free"], "embeddings": ["POST /v1/embeddings (501 honest if no upstream configured)"], "agent": ["POST /v1/search", "POST /v1/decision", "GET/POST /v1/knowledge/*"],
        },
        "notes": [
            "Gratis/controlado (FREE_ONLY) ≠ ilimitado: proveedores aplican cuotas/rate limits/créditos/capacidad.",
            "Usa model=\"auto\"; temperature=0 habilita caché para respuestas repetibles; max_tokens reduce latencia.",
        ],
    }





async def _free_response(_: bool = Depends(require_api_key_flexible)):
    providers, models = await catalog()
    ctrl = free_control_info()
    def is_free_id(m):
        mid = (m.get('id') or '').lower(); up = (m.get('upstream_model') or '').lower(); prov=(m.get('provider') or '').lower()
        return prov=='pollinations' or ':free' in mid or ':free' in up or mid.endswith('/free') or (prov=='openrouter' and up=='free')
    free_models = [m for m in models if m.get('id')!='auto' and is_free_id(m)]
    return {
        'object':'free_control','status':'ok','time':int(time.time()),
        'free_control': ctrl,
        'summary': {
            'total_models_listed': len(models),
            'clearly_free_models_listed': len(free_models),
            'active_providers': [p['id'] for p in providers if p.get('active')],
            'note': 'Listado "claramente gratuito" usa señales explícitas (:free/anónimo). Proveedores con cuenta propia pueden tener cuotas/créditos; el control FREE_ONLY bloquea candidatos no marcados como free-tier.',
        },
        'clearly_free_models': [{'id':m['id'],'provider':m['provider'],'note':m.get('note','')} for m in free_models[:300]],
    }

for path in ['/v1/free','/free','/openai/v1/free','/api/v1/free']:
    app.add_api_route(path, _free_response, methods=["GET","POST"], dependencies=[Depends(require_api_key_flexible)])

async def _status_response(_: bool = Depends(require_api_key_flexible)):
    providers, models = await catalog()
    active = [p["id"] for p in providers if p.get("active")]
    rt = runtime_status()
    return {
        "object": "status",
        "status": "ok",
        "time": int(time.time()),
        "version": app.version,
        "service": "free-ai-gateway",
        "public_access": {
            "direct_base_url": "http://109.123.248.91:8000/v1",
            "recommended": "Use HTTPS reverse proxy (deploy/apache-free-ai-gateway.conf + DNS + certbot).",
            "limitation": "Port 8000 may be blocked by provider/VPS firewall; free upstream tiers have quotas/rate limits/credits.",
        },
        "active_providers": active,
        "providers": providers,
        "models_count": len(models),
        "cache": response_cache.info(),
        "runtime": rt,
        "free_control": free_control_info(),
        "auth_modes": ["Authorization: Bearer <key>", "api-key", "x-api-key", "key", "?api_key/?key"],
        "compatibility": {"base_urls": ["/v1","/openai/v1","/api/v1"], "inputs": ["messages","prompt","input"], "token_limits": ["max_tokens","max_completion_tokens"], "model": "auto recommended"},
    }

for path in ["/v1/status", "/status", "/openai/v1/status", "/api/v1/status"]:
    app.add_api_route(path, _status_response, methods=["GET","POST"], dependencies=[Depends(require_api_key_flexible)])



async def _audit_response(_: bool = Depends(require_api_key_flexible)):
    providers, models = await catalog(refresh=False)
    ctrl = free_control_info()
    rt = runtime_status()
    def free_sig(m):
        mid=(m.get('id') or '').lower(); up=(m.get('upstream_model') or '').lower(); prov=(m.get('provider') or '').lower()
        return prov=='pollinations' or ':free' in mid or ':free' in up or mid.endswith('/free') or (prov=='openrouter' and up=='free')
    clearly=[m for m in models if m.get('id')!='auto' and free_sig(m)]
    active=[p for p in providers if p.get('active')]
    return {
        'object':'audit','status':'ok','time':int(time.time()),
        'efficiency': {'catalog_cache_ttl_s': rt.get('catalog_ttl_s'), 'catalog_cache_age_s': rt.get('catalog_cache_age_s'), 'response_cache': response_cache.info()},
        'intelligence': {'smart_routing': True, 'health_latency_scoring': True, 'cooldowns_active': len(rt.get('cooldowns') or {}), 'auto_candidates': rt.get('auto_candidates')},
        'free_audit': {
            **ctrl,
            'active_providers': [{'id':p['id'],'label':p.get('label'),'always_on':p.get('always_on')} for p in active],
            'clearly_free_models_count': len(clearly),
            'sample_clearly_free': [m['id'] for m in clearly[:20]],
            'verdict': 'POLICY_FREE_ONLY' if ctrl.get('free_only') else 'USER_OPT_IN_MODE',
            'honest_note': 'Controlado por política/allowlist/metadatos. No hay prueba universal de gratuidad ilimitada upstream; proveedores aplican cuotas/rate limits/créditos/capacidad.',
        },
    }

for path in ['/v1/audit','/audit','/openai/v1/audit','/api/v1/audit']:
    app.add_api_route(path, _audit_response, methods=["GET","POST"], dependencies=[Depends(require_api_key_flexible)])

async def _models_response(_: bool = Depends(require_api_key_flexible)):
    providers, models = await catalog()
    data = [{
        "id": m["id"], "object": "model", "created": 0, "owned_by": m["owned_by"],
        "provider": m["provider"], "free": m.get("free", True), "capabilities": m.get("capabilities", []),
        "note": m.get("note", ""),
    } for m in models]
    return {"object": "list", "providers": providers, "data": data}

for path in ["/v1/models", "/models", "/openai/v1/models", "/api/v1/models"]:
    app.add_api_route(path, _models_response, methods=["GET","POST"], dependencies=[Depends(require_api_key_flexible)])

async def _providers_response(_: bool = Depends(require_api_key_flexible)):
    providers, _ = await catalog()
    return {"object": "list", "data": providers}

for path in ["/v1/providers", "/providers", "/openai/v1/providers", "/api/v1/providers"]:
    app.add_api_route(path, _providers_response, methods=["GET","POST"], dependencies=[Depends(require_api_key_flexible)])

async def _cache_info(_: bool = Depends(require_api_key_flexible)):
    return {"object": "cache", **response_cache.info()}

async def _cache_clear(_: bool = Depends(require_api_key_flexible)):
    n = response_cache.clear()
    return {"object": "cache.clear", "cleared": n, **response_cache.info()}

for path in ["/v1/cache", "/cache", "/openai/v1/cache", "/api/v1/cache"]:
    app.add_api_route(path, _cache_info, methods=["GET"], dependencies=[Depends(require_api_key_flexible)])
for path in ["/v1/cache/clear", "/cache/clear", "/openai/v1/cache/clear", "/api/v1/cache/clear"]:
    app.add_api_route(path, _cache_clear, methods=["POST", "DELETE"], dependencies=[Depends(require_api_key_flexible)])

def _apply_cache_headers(data: dict[str, Any], *, hit: bool, key: str | None = None) -> dict[str, Any]:
    data.setdefault("gateway", {})
    data["gateway"]["cache"] = {"hit": hit, "enabled": bool(getattr(settings, 'cache_enabled', True)), "ttl_seconds": int(getattr(settings, 'cache_ttl_seconds', 300))}
    if key:
        data["gateway"]["cache"]["key"] = key[:16]
    return data



async def _embeddings_response(request: Request, _: bool = Depends(require_api_key_flexible)):
    # Honest compatibility: this gateway aggregates chat/free text sources; embeddings providers
    # are not configured here. Clients should use a dedicated embeddings endpoint/provider.
    try:
        body = await request.json()
    except Exception:
        body = {}
    raise HTTPException(status_code=501, detail={
        'message': 'Embeddings not supported by this free gateway instance. Configure a dedicated embeddings-compatible upstream or use a provider embeddings API directly.',
        'type': 'unsupported_feature',
        'code': 501,
        'requested_model': (body or {}).get('model') if isinstance(body, dict) else None,
        'suggestion': 'Use /v1/chat/completions, /v1/responses, /v1/search, or /v1/decision; add an embeddings upstream if needed.',
    })

for path in ['/v1/embeddings', '/embeddings', '/openai/v1/embeddings', '/api/v1/embeddings']:
    app.add_api_route(path, _embeddings_response, methods=['POST'], dependencies=[Depends(require_api_key_flexible)])

async def _chat(request: Request, _: bool = Depends(require_api_key_flexible)):
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    payload = _normalize_payload(raw)
    before_chars = 0
    try:
        before_chars = sum(len(str(m.get('content',''))) for m in (payload.get('messages') or []) if isinstance(m, dict))
    except Exception:
        pass
    optimized = compress_messages(copy.deepcopy(payload))
    payload_for_cache = copy.deepcopy(optimized)
    key = cache_key(payload_for_cache) if cacheable(payload_for_cache) else None
    if key:
        cached = response_cache.get(key)
        if cached:
            cached.setdefault("gateway", {})
            cached["gateway"].setdefault("context", {})
            if optimized.get("gateway", {}).get("context_compressed"):
                cached["gateway"]["context"] = {k: v for k, v in optimized["gateway"].items() if k.startswith('context') or k in ('messages_before','messages_after','mode')}
            _apply_cache_headers(cached, hit=True, key=key)
            return JSONResponse(cached)
    stream = bool(optimized.get("stream"))
    # helpful for coding agents/SDKs: request usage in stream when supported
    if stream and isinstance(optimized.get('stream_options'), dict) is False and optimized.get('stream_options') is None:
        optimized['stream_options'] = {'include_usage': True}

    try:
        if stream:
            async def gen():
                try:
                    async for chunk in stream_with_fallback(optimized):
                        yield chunk
                except ProviderError as e:
                    err = {"error": {"message": str(e), "type": "provider_error", "provider": e.provider, "code": e.status}}
                    yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode()
                    yield b"data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        data, _ = await execute_with_fallback(optimized)
        data.setdefault("object", "chat.completion")
        data.setdefault("created", int(time.time()))
        data.setdefault("gateway", {})
        if optimized.get("gateway", {}).get("context_compressed"):
            data["gateway"]["context"] = {k: v for k, v in optimized["gateway"].items() if k.startswith('context') or k in ('messages_before','messages_after','mode')}
        else:
            data["gateway"]["context"] = {"context_compressed": False, "context_chars_before": before_chars}
        _apply_cache_headers(data, hit=False, key=key)
        if key and isinstance(data, dict) and data.get("choices"):
            response_cache.set(key, data, int(getattr(settings, 'cache_ttl_seconds', 300)))
        return JSONResponse(data)
    except ProviderError as e:
        detail = {"message": str(e), "type": "provider_error", "provider": e.provider, "model": optimized.get("model"), "code": e.status}
        atts = getattr(e, 'attempts', None)
        if atts:
            detail["attempts"] = atts
            detail["attempt_count"] = len(atts)
        raise HTTPException(status_code=e.status, detail=detail)

for path in [
    "/v1/chat/completions", "/chat/completions", "/openai/v1/chat/completions", "/api/v1/chat/completions",
    "/v1/completions", "/completions",
]:
    app.add_api_route(path, _chat, methods=["POST"], dependencies=[Depends(require_api_key_flexible)])



@app.get('/readyz')
@app.head('/readyz')
@app.get('/v1/readyz')
@app.head('/v1/readyz')
async def readyz():
    # lightweight readiness (no upstream calls)
    return {'status':'ready','time':int(time.time()),'version':app.version}

async def _metrics_response(_: bool = Depends(require_api_key_flexible)):
    return {'object':'metrics','time':int(time.time()), **metrics.snapshot(), 'runtime': runtime_status(), 'free_control': free_control_info()}

for path in ['/v1/metrics','/metrics']:
    app.add_api_route(path, _metrics_response, methods=["GET","POST"], dependencies=[Depends(require_api_key_flexible)])


def _responses_to_chat(body: dict[str, Any]) -> dict[str, Any]:
    # Minimal OpenAI Responses -> Chat Completions compatibility for common clients.
    out = dict(body)
    if 'messages' not in out:
        inp = out.pop('input', None)
        msgs = []
        if isinstance(inp, str):
            msgs = [{'role':'user','content':inp}]
        elif isinstance(inp, list):
            for item in inp:
                if isinstance(item, dict):
                    role = item.get('role') or 'user'
                    c = item.get('content')
                    if isinstance(c, list):
                        parts = []
                        for x in c:
                            if isinstance(x, dict):
                                parts.append(str(x.get('text') or x.get('input_text') or x.get('output_text') or ''))
                            else:
                                parts.append(str(x))
                        c = '\n'.join([p for p in parts if p])
                    if c is not None:
                        msgs.append({'role': role, 'content': c if isinstance(c, str) else str(c)})
        if not msgs and out.get('instructions'):
            msgs = [{'role':'system','content':str(out.pop('instructions'))}]
        if msgs:
            out['messages'] = msgs
    out.setdefault('model','auto')
    if 'max_output_tokens' in out and 'max_tokens' not in out:
        out['max_tokens'] = out.pop('max_output_tokens')
    return out

async def _responses(request: Request, _: bool = Depends(require_api_key_flexible)):
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON body')
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail='Body must be a JSON object')
    chat = _responses_to_chat(raw)
    # non-stream returns a lightweight Responses-shaped envelope
    if not chat.get('stream'):
        chat['stream'] = False
        # reuse chat handler logic by normalizing through _chat internals: call execute path
        before_chars = 0
        try:
            before_chars = sum(len(str(m.get('content',''))) for m in (chat.get('messages') or []) if isinstance(m, dict))
        except Exception:
            pass
        optimized = compress_messages(copy.deepcopy(chat))
        payload_for_cache = copy.deepcopy(optimized)
        key = cache_key(payload_for_cache) if cacheable(payload_for_cache) else None
        if key:
            cached = response_cache.get(key)
            if cached:
                m=((cached.get('choices') or [{}])[0].get('message') or {}); text = m.get('content') or m.get('reasoning') or ''
                resp = {'id': cached.get('id') or f"resp_{uuid.uuid4().hex[:24]}", 'object':'response','created_at':cached.get('created') or int(time.time()),'model':cached.get('model'),'status':'completed','output_text':text,'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}],'gateway':{**(cached.get('gateway') or {}), 'cache':{'hit':True}}}
                return JSONResponse(resp)
        try:
            data, _ = await execute_with_fallback(optimized)
        except ProviderError as e:
            detail = {"message": str(e), "type": "provider_error", "provider": e.provider, "model": optimized.get("model"), "code": e.status}
            atts = getattr(e, 'attempts', None)
            if atts: detail["attempts"] = atts; detail["attempt_count"] = len(atts)
            raise HTTPException(status_code=e.status, detail=detail)
        m=((data.get('choices') or [{}])[0].get('message') or {}); text = m.get('content') or m.get('reasoning') or ''
        resp = {'id': f"resp_{uuid.uuid4().hex[:24]}", 'object':'response','created_at':data.get('created') or int(time.time()),'model':data.get('model'),'status':'completed','output_text':text,'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}],'usage':data.get('usage'),'gateway':data.get('gateway')}
        if key and text:
            response_cache.set(key, data, int(getattr(settings, 'cache_ttl_seconds', 300)))
        return JSONResponse(resp)
    # stream fallback as chat SSE (clients expecting Responses streaming should tolerate; best-effort)
    chat['stream'] = True
    async def gen():
        try:
            async for chunk in stream_with_fallback(chat):
                yield chunk
        except ProviderError as e:
            err = {"error": {"message": str(e), "type": "provider_error", "provider": e.provider, "code": e.status}}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n".encode(); yield b"data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type='text/event-stream', headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

for path in ['/v1/responses','/responses','/openai/v1/responses']:
    app.add_api_route(path, _responses, methods=['POST'], dependencies=[Depends(require_api_key_flexible)])



async def _search(request: Request, _: bool = Depends(require_api_key_flexible)):
    try: raw = await request.json() if request.method == 'POST' else {}
    except Exception: raw = {}
    if request.method == 'GET':
        q = request.query_params.get('q') or request.query_params.get('query') or ''
        provider = request.query_params.get('provider') or 'auto'
        n = request.query_params.get('max_results') or request.query_params.get('n') or '5'
        return await web_search(q, max_results=int(n), provider=provider)
    q = (raw.get('query') or raw.get('q') or raw.get('search') or '') if isinstance(raw, dict) else ''
    provider = (raw.get('provider') or 'auto') if isinstance(raw, dict) else 'auto'
    n = (raw.get('max_results') or raw.get('n') or 5) if isinstance(raw, dict) else 5
    return await web_search(str(q), max_results=int(n), provider=str(provider))

for path in ['/v1/search','/search','/v1/tools/search','/openai/v1/search']:
    app.add_api_route(path, _search, methods=['GET','POST'], dependencies=[Depends(require_api_key_flexible)])

async def _kb_search(request: Request, _: bool = Depends(require_api_key_flexible)):
    if request.method == 'GET':
        q = request.query_params.get('q') or ''; n = request.query_params.get('n') or '5'; return kb_query(q, limit=int(n))
    try: raw = await request.json()
    except Exception: raw = {}
    return kb_query(str((raw or {}).get('query') or (raw or {}).get('q') or ''), limit=int((raw or {}).get('limit') or (raw or {}).get('n') or 5))

async def _kb_add(request: Request, _: bool = Depends(require_api_key_flexible)):
    try: raw = await request.json()
    except Exception: raise HTTPException(status_code=400, detail='Invalid JSON body')
    if not isinstance(raw, dict): raise HTTPException(status_code=400, detail='Body must be a JSON object')
    item = kb_add(title=str(raw.get('title') or raw.get('query') or 'source'), url=str(raw.get('url') or ''), content=str(raw.get('content') or raw.get('text') or ''), tags=raw.get('tags') if isinstance(raw.get('tags'), list) else [], source=str(raw.get('source') or 'api'), meta=raw.get('meta') if isinstance(raw.get('meta'), dict) else {})
    return {'object':'knowledge.item','item':item, **kb_stats()}

async def _kb_stats(_: bool = Depends(require_api_key_flexible)):
    return kb_stats()

for path in ['/v1/knowledge/search','/knowledge/search']: app.add_api_route(path, _kb_search, methods=['GET','POST'], dependencies=[Depends(require_api_key_flexible)])
for path in ['/v1/knowledge/add','/knowledge/add']: app.add_api_route(path, _kb_add, methods=['POST'], dependencies=[Depends(require_api_key_flexible)])
for path in ['/v1/knowledge','/knowledge']: app.add_api_route(path, _kb_stats, methods=['GET'], dependencies=[Depends(require_api_key_flexible)])

async def _decision(request: Request, _: bool = Depends(require_api_key_flexible)):
    """Decision/agent helper: optionally searches, compresses evidence, then asks auto model."""
    try: raw = await request.json()
    except Exception: raise HTTPException(status_code=400, detail='Invalid JSON body')
    if not isinstance(raw, dict): raise HTTPException(status_code=400, detail='Body must be a JSON object')
    objective = str(raw.get('objective') or raw.get('query') or raw.get('prompt') or '').strip()
    if not objective: raise HTTPException(status_code=400, detail='Missing objective/query')
    do_search = bool(raw.get('search', True))
    evidence = []
    search_result = None
    if do_search:
        search_result = await web_search(objective, max_results=int(raw.get('max_results') or 5), provider=str(raw.get('search_provider') or 'auto'))
        for r in (search_result.get('results') or [])[:5]:
            evidence.append(f"- {r.get('title','')}\n  {r.get('url','')}\n  {str(r.get('snippet',''))[:500]}")
            try: kb_add(title=r.get('title') or objective[:80], url=r.get('url') or '', content=r.get('snippet') or '', tags=['search','decision'], source='web-search', meta={'objective': objective[:200]})
            except Exception as e:
                import logging
                logging.getLogger("free-ai").warning("kb_add failed: %s", e)
    kb = kb_query(objective, limit=3)
    for r in (kb.get('results') or [])[:3]:
        evidence.append(f"- [KB] {r.get('title','')}\n  {r.get('url','')}\n  {str(r.get('content',''))[:400]}")
    messages = raw.get('messages') if isinstance(raw.get('messages'), list) else []
    if not messages:
        messages = [
            {'role':'system','content':'Eres un motor de decisión robusto. Usa evidencia disponible, cita URLs cuando existan, separa hechos de inferencias, y declara incertidumbre/limitaciones. Responde útil, eficiente y verificable.'},
            {'role':'user','content': f"Objetivo: {objective}\n\nEvidencia recopilada:\n" + ("\n".join(evidence) if evidence else "(sin evidencia web/KB disponible; responde con cautela)") + "\n\nEntrega: decisión/recomendación, pasos, riesgos, fuentes."}
        ]
    payload = {'model': raw.get('model') or 'auto', 'messages': messages, 'temperature': raw.get('temperature', 0.2), 'max_tokens': raw.get('max_tokens', 4000), 'cache': raw.get('cache', False)}
    optimized = compress_messages(copy.deepcopy(payload))
    try:
        data, _ = await execute_with_fallback(optimized)
        msg=((data.get('choices') or [{}])[0].get('message') or {}); answer = msg.get('content') or ''
        if not answer and not msg.get('tool_calls'): answer = msg.get('reasoning') or msg.get('reasoning_content') or ''
        return {'object':'decision','ok': bool(answer),'objective':objective,'answer':answer or '','search':search_result,'knowledge':{'matches':kb.get('count',0)},'gateway':data.get('gateway'),'model':data.get('model')}
    except ProviderError as e:
        detail = {"message": str(e), "type": "provider_error", "provider": e.provider, "code": e.status}
        atts = getattr(e,'attempts',None);
        if atts: detail['attempts']=atts
        raise HTTPException(status_code=e.status, detail=detail)

for path in ['/v1/decision','/decision','/v1/agent/decision']:
    app.add_api_route(path, _decision, methods=['POST'], dependencies=[Depends(require_api_key_flexible)])

@app.get("/v1")
@app.get("/openai/v1")
@app.get("/api/v1")
async def v1_root(_: bool = Depends(require_api_key_flexible)):
    return {"object": "api", "name": "Free AI Gateway", "openai_compatible": True, "endpoints": ["/v1/models", "/v1/chat/completions", "/v1/cache"]}


@app.get("/v1/tools")
@app.get("/openai/v1/tools")
@app.get("/api/v1/tools")
async def tools_list(request: Request):
    """List all standard OpenAI-compatible tool definitions."""
    from .tools import get_all_tool_definitions
    all_tools = get_all_tool_definitions()
    return {
        "object": "tools",
        "tools": all_tools,
        "count": len(all_tools),
        "description": "Standard OpenAI-compatible tool definitions for function calling",
    }


@app.get("/v1/telemetry")
@app.get("/telemetry")
@app.get("/openai/v1/telemetry")
async def telemetry_response():
    from .telemetry import telemetry
    return await telemetry()


@app.get("/v1/connections")
@app.get("/connections")
@app.get("/openai/v1/connections")
async def connections_response():
    return metrics.snapshot()


@app.get("/v1/debug")
@app.get("/debug")
@app.get("/openai/v1/debug")
async def debug_response():
    from .telemetry import telemetry
    t = await telemetry()
    return {
        "object": "debug",
        "time": t.get("time"),
        "requests": t.get("requests"),
        "runtime": t.get("runtime"),
        "cache": t.get("cache"),
        "free_control": t.get("free_control"),
        "limits": t.get("limits"),
    }


# --- Project generation (ForthTrade IA generates; temp output) ---
from .project_gen import generate_one as _project_generate_one

async def _project_generate(request: Request, _: bool = Depends(require_api_key_flexible)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail=_openai_error('Invalid JSON body', type_='invalid_request_error', code=400, request_id=getattr(request.state,'request_id','')))
    prompt = (body.get('prompt') or body.get('objective') or '').strip()
    if not prompt:
        raise HTTPException(status_code=400, detail=_openai_error('prompt/objective required', type_='invalid_request_error', code=400, param='prompt', request_id=getattr(request.state,'request_id','')))
    name = str(body.get('name') or 'generated-project')[:120]
    model = str(body.get('model') or 'auto')
    if getattr(settings, 'free_only', True) and model != 'auto' and not any(x in model.lower() for x in [':free','/free','pollinations/']):
        raise HTTPException(status_code=403, detail=_openai_error(f'FREE_ONLY blocks non-free model selection: {model}', type_='forbidden', code=403, request_id=getattr(request.state,'request_id','')))
    res = await _project_generate_one(
        prompt=prompt, name=name, model=model,
        max_tokens=max(256, min(8192, int(body.get('max_tokens') or 4000))),
        temperature=float(body.get('temperature') or 0),
        max_retries=max(1, min(4, int(body.get('max_retries') or 2))),
        retry_delay_s=max(0, min(180, float(body.get('retry_delay_s') or 55))),
        keep_temp=bool(body.get('keep_temp') or False),
    )
    return {'object':'project_generation','status':'ok' if res.get('ok') else 'failed','time':int(time.time()), **res}

for path in ['/v1/projects/generate','/v1/project/generate','/projects/generate']:
    app.add_api_route(path, _project_generate, methods=['POST'], dependencies=[Depends(require_api_key_flexible)])
