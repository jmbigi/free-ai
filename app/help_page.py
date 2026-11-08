from __future__ import annotations
import html, json

BASE = "https://ia.forthtrade.com"  # overridden by settings.public_base_url in callers
KEY_ENV = "FT_AI_API_KEY"


def help_payload(base_url: str = BASE) -> dict:
    base = base_url.rstrip('/')
    v1 = f"{base}/v1"
    curl = (
        f"curl -sS {v1}/chat/completions "
        f"-H \"Authorization: Bearer ${KEY_ENV}\" -H 'Content-Type: application/json' "
        f"-d '{{\"model\":\"auto\",\"messages\":[{{\"role\":\"user\",\"content\":\"Hola\"}}],\"max_tokens\":64,\"temperature\":0}}'"
    )
    return {
        "service": "Free AI Gateway",
        "status": "ok",
        "public_base_url": base,
        "openai_base_url": v1,
        "recommended_env": KEY_ENV,
        "model": "auto",
        "auth": {
            "recommended_env": KEY_ENV,
            "accepted_env": ["FT_AI_API_KEY", "API_KEY", "FREE_AI_API_KEY", "GATEWAY_API_KEY"],
            "accepted_headers": ["Authorization: Bearer <key>", "api-key: <key>", "x-api-key: <key>"],
            "accepted_query": ["key", "api_key (tests only; prefer headers)"],
            "note": "Una sola API key del gateway. Nunca uses claves upstream en clientes. Rota la clave si se expuso.",
        },
        "capabilities": {
            "openai_compatible": True,
            "chat_completions": True,
            "responses_basic": True,
            "tool_calling": True,
            "stream_sse": True,
            "input_aliases": ["messages", "prompt", "input"],
            "token_aliases": ["max_tokens", "max_completion_tokens", "max_output_tokens"],
            "auto_fallback": True,
            "cache": True,
            "context_compression": True,
            "free_only_policy": True,
            "observability": ["x-request-id", "x-gateway-version", "/readyz", "/v1/metrics", "/v1/audit", "/v1/status"],
            "limitation": "Gratis/controlado ≠ ilimitado. Los proveedores upstream imponen cuotas, rate limits, créditos o capacidad variable.",
        },
        "endpoints": {
            "help_html": f"{base}/help",
            "help_json": f"{base}/help.json",
            "health": f"{base}/health",
            "readyz": f"{base}/readyz",
            "models": f"{v1}/models",
            "chat_completions": f"{v1}/chat/completions",
            "responses": f"{v1}/responses",
            "chat_with_tools": f"{v1}/chat/completions (tools/tool_choice, legacy functions)",
            "providers": f"{v1}/providers",
            "audit": f"{v1}/audit",
            "free": f"{v1}/free",
            "cache": f"{v1}/cache",
            "metrics_auth": f"{v1}/metrics",
            "projects_generate": f"{v1}/projects/generate",
        },
        "quick_test": curl,
        "clients": {
            "opencode": {
                "type": "OpenAI-compatible/custom provider",
                "base_url": v1,
                "api_key": f"${KEY_ENV}",
                "model": "auto",
                "config_example": {"provider": "openai-compatible", "baseURL": v1, "apiKey": f"${KEY_ENV}", "model": "auto"},
                "notes": "Usa el gateway como endpoint compatible. No configures claves upstream en OpenCode.",
            },
            "kimicode_kimi": {
                "type": "Kimi Code / harness OpenAI-compatible",
                "base_url": v1,
                "api_key": f"${KEY_ENV}",
                "model": "auto",
                "notes": "Apunta al gateway con la API key del gateway. No se requiere clave Kimi/Moonshot en el cliente para usar el gateway; Kimi/Moonshot upstream depende de configuración/cuenta/política del servidor.",
            },
            "deepseek_harness": {
                "type": "DeepSeek/OpenAI-compatible harness",
                "base_url": v1,
                "api_key": f"${KEY_ENV}",
                "model": "auto",
                "env_example": {"OPENAI_BASE_URL": v1, "OPENAI_API_KEY": f"${KEY_ENV}", KEY_ENV: "TU_API_KEY_GATEWAY"},
                "notes": "Si el harness usa variables DeepSeek específicas, pon la URL/key del gateway donde corresponda y model=auto.",
            },
            "kilocode": {
                "type": "KiloCode OpenAI Compatible / OpenAI API",
                "base_url": v1,
                "api_key": f"${KEY_ENV}",
                "model": "auto",
                "ui_values": {"Base URL": v1, "API Key": f"${KEY_ENV}", "Model": "auto"},
                "notes": "Puedes exportar FT_AI_API_KEY y referenciarla en tu entorno/configuración si el cliente lo soporta.",
            },
        },
    }


def render_help_html(base_url: str = BASE) -> str:
    d = help_payload(base_url)
    j = html.escape(json.dumps(d, ensure_ascii=False, indent=2))
    v1 = html.escape(d['openai_base_url'])
    key = html.escape(KEY_ENV)
    pub = html.escape(d['public_base_url'])
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free AI Gateway — Conexión</title>
<style>
:root{{--bg:#060b16;--p:#0d1728;--b:#1d3258;--t:#eaf2ff;--m:#98b2d8;--a:#22c55e;--c:#38bdf8;--w:#f59e0b}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.55 system-ui,Segoe UI,Arial;background:radial-gradient(900px 400px at 10% -10%,#132a52,transparent),var(--bg);color:var(--t)}}
.w{{max-width:1180px;margin:0 auto;padding:22px}} .hero{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}}
.card{{background:rgba(13,23,40,.94);border:1px solid var(--b);border-radius:16px;padding:16px;margin:12px 0}}
h1{{margin:0;font-size:30px}} h2{{margin:0 0 8px;font-size:18px;color:#d7e7ff}} .m{{color:var(--m)}}
code,pre{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
pre{{white-space:pre-wrap;word-break:break-word;background:#081120;border:1px solid var(--b);border-radius:12px;padding:12px;margin:8px 0;overflow:auto}}
code{{background:#081120;border:1px solid var(--b);padding:1px 6px;border-radius:6px}}
.k{{display:inline-block;padding:3px 9px;border:1px solid #24463a;color:#86efac;background:#081a12;border-radius:999px;font-size:12px;margin:3px 6px 0 0}}
a{{color:#7dd3fc;text-decoration:none}} .g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
.warn{{border-color:#5f4817;background:rgba(74,49,10,.16)}} .ok{{border-color:#24533a}}
table{{width:100%;border-collapse:collapse}} td,th{{border-bottom:1px solid var(--b);padding:8px;text-align:left;vertical-align:top}} th{{color:#d7e7ff}}
</style></head><body><div class="w">
<div class="hero"><div><h1>Free AI Gateway — Conexión</h1><p class="m">Gateway OpenAI-compatible, productivo y robusto. Una sola API key del gateway, <code>model=auto</code>, fallback, caché, compresión y control <code>FREE_ONLY</code>.</p></div>
<div><a class="k" href="/">Playground</a><a class="k" href="/docs">Swagger</a><a class="k" href="/health">Health</a><a class="k" href="/readyz">Ready</a></div></div>
<div class="card ok"><span class="k">Public</span> <code>{pub}</code> &nbsp; <span class="k">Base URL</span> <code>{v1}</code><br>
<span class="k">API Key env</span> <code>{key}</code> &nbsp; <span class="k">Model</span> <code>auto</code> &nbsp; <span class="k">Auth</span> <code>Authorization: Bearer ${key}</code></div>
<div class="card"><h2>Exportar clave (cliente)</h2><pre>export {key}="TU_API_KEY_GATEWAY"
# El gateway acepta también API_KEY/FREE_AI_API_KEY/GATEWAY_API_KEY; recomendado: {key}</pre></div>
<div class="g">
<div class="card"><h2>OpenCode</h2><pre># Proveedor OpenAI-compatible / custom
baseURL = "{v1}"
apiKey  = "${key}"   # o valor directo
model   = "auto"</pre><p class="m">Configura el gateway como endpoint compatible. No uses claves upstream.</p></div>
<div class="card"><h2>Kimi Code / Kimi</h2><pre># Cliente/harness OpenAI-compatible
base_url = "{v1}"
api_key  = "${key}"
model    = "auto"</pre><p class="m">Apunta al gateway con la key del gateway. Kimi/Moonshot upstream depende de la configuración/política del servidor.</p></div>
<div class="card"><h2>DeepSeek harness</h2><pre>export {key}="TU_API_KEY_GATEWAY"
export OPENAI_BASE_URL="{v1}"
export OPENAI_API_KEY="${key}"
# model=auto</pre><p class="m">Para harnesses OpenAI-compatible. Si usa variables propias, coloca ahí la URL/key del gateway.</p></div>
<div class="card"><h2>KiloCode</h2><pre>Provider: OpenAI Compatible / OpenAI API
Base URL: {v1}
API Key:  ${key}
Model:    auto</pre><p class="m">Usa la API key del gateway (valor o variable {key}).</p></div>
</div>
<div class="card"><h2>Herramientas / function calling</h2><p class="m">Compatible con <code>tools</code>/<code>tool_choice</code> y legacy <code>functions</code>/<code>function_call</code>. El gateway preserva tool calls y aplica compatibilidad cuando el proveedor upstream es limitado.</p><pre>{{"model":"auto","messages":[{{"role":"user","content":"Weather in Paris?"}}],"tools":[{{"type":"function","function":{{"name":"get_weather","parameters":{{"type":"object","properties":{{"city":{{"type":"string"}}}},"required":["city"]}}}}}}],"tool_choice":"auto"}}</pre></div>
<div class="card"><h2>Prueba rápida</h2><pre>export {key}="TU_API_KEY_GATEWAY"
curl -sS {v1}/chat/completions \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"model":"auto","messages":[{{"role":"user","content":"Hola"}}],"max_tokens":64,"temperature":0}}'</pre></div>
<div class="card"><h2>Endpoints útiles</h2><table><tr><th>Endpoint</th><th>Uso</th></tr>
<tr><td><code>POST /v1/chat/completions</code></td><td>Chat OpenAI-compatible (recomendado)</td></tr>
<tr><td><code>POST /v1/responses</code></td><td>Compatibilidad básica Responses API</td></tr>
<tr><td><code>GET /v1/models</code></td><td>Catálogo (auth)</td></tr>
<tr><td><code>GET /v1/metrics</code></td><td>Latencia/errores/uptime (auth)</td></tr>
<tr><td><code>GET /v1/audit</code></td><td>Auditoría FREE_ONLY/eficiencia (auth)</td></tr>
<tr><td><code>GET /health</code>, <code>/readyz</code></td><td>Sondeos rápidos</td></tr></table></div>
<div class="card warn"><h2>Limitaciones reales (obligatorias)</h2><p class="m"><b>Gratis/controlado ≠ ilimitado.</b> <code>FREE_ONLY</code> prioriza fuentes free-tier/anónimas explícitas; proveedores upstream imponen cuotas, rate limits, créditos, términos o capacidad variable. El gateway hace fallback, caché y control, pero <b>no puede garantizar inferencia remota avanzada gratuita ilimitada</b>. Rota la API key si se expuso. No envíes claves upstream a clientes.</p></div>
<div class="card"><h2>Ayuda JSON</h2><p class="m"><a href="/help.json">/help.json</a> · <a href="/v1/help">/v1/help</a></p><pre>{j}</pre></div>
</div></body></html>'''

# tool calling note appended? easier to patch via python
