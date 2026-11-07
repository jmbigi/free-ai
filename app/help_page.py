from __future__ import annotations
import html, json

BASE = "https://ia.forthtrade.com"
KEY_ENV = "FT_AI_API_KEY"  # user-facing env var name; server also accepts API_KEY


def help_payload(base_url: str = BASE) -> dict:
    base = base_url.rstrip('/')
    return {
        "service": "Free AI Gateway",
        "status": "ok",
        "public_base_url": base,
        "openai_base_url": f"{base}/v1",
        "auth": {
            "recommended_env": KEY_ENV,
            "accepted_env": ["FT_AI_API_KEY", "API_KEY", "FREE_AI_API_KEY", "GATEWAY_API_KEY"],
            "accepted_headers": ["Authorization: Bearer <key>", "api-key: <key>", "x-api-key: <key>"],
            "accepted_query": ["key", "api_key", "apikey"],
            "note": "Una sola API key del gateway. No usar claves upstream (OpenRouter/DeepSeek/Kimi/etc.). Rotar si se expuso.",
        },
        "model": {"recommended": "auto", "note": "auto usa fallback + caché + compresión + control FREE_ONLY. Gratis/controlado ≠ ilimitado (cuotas/rate limits/capacidad)."},
        "endpoints": {
            "health": f"{base}/health",
            "help": f"{base}/help",
            "help_json": f"{base}/v1/help",
            "models": f"{base}/v1/models",
            "chat_completions": f"{base}/v1/chat/completions",
            "openai_alias": f"{base}/openai/v1/chat/completions",
            "providers": f"{base}/v1/providers",
            "audit": f"{base}/v1/audit",
            "free": f"{base}/v1/free",
            "cache": f"{base}/v1/cache",
        },
        "quick_test": f"curl -sS {base}/v1/chat/completions -H \"Authorization: Bearer ${KEY_ENV}\" -H 'Content-Type: application/json' -d '{{\"model\":\"auto\",\"messages\":[{{\"role\":\"user\",\"content\":\"Hola\"}}],\"max_tokens\":64,\"temperature\":0}}'",
        "clients": {
            "opencode": {
                "base_url": f"{base}/v1",
                "api_key_env": KEY_ENV,
                "model": "auto",
                "notes": "Configura proveedor OpenAI-compatible/custom con base URL del gateway y la API key del gateway. Si OpenCode pide OPENAI_API_KEY/clave genérica, usa el valor de FT_AI_API_KEY.",
            },
            "kimicode_kimi": {
                "base_url": f"{base}/v1",
                "api_key_env": KEY_ENV,
                "model": "auto",
                "notes": "Usa endpoint OpenAI-compatible del gateway. No requiere clave Kimi/Moonshot del cliente cuando apuntas al gateway; el gateway enruta según FREE_ONLY/cuentas upstream configuradas.",
            },
            "deepseek_harness": {
                "base_url": f"{base}/v1",
                "api_key_env": KEY_ENV,
                "model": "auto",
                "notes": "Cualquier harness compatible con chat.completions/OpenAI: base_url + Bearer FT_AI_API_KEY + model auto.",
            },
            "kilocode": {
                "base_url": f"{base}/v1",
                "api_key_env": KEY_ENV,
                "model": "auto",
                "notes": "Proveedor OpenAI-compatible/OpenAI API: Base URL https://ia.forthtrade.com/v1, API Key = FT_AI_API_KEY del gateway, modelo auto.",
            },
        },
    }


def render_help_html(base_url: str = BASE) -> str:
    d = help_payload(base_url)
    j = html.escape(json.dumps(d, ensure_ascii=False, indent=2))
    base = html.escape(d['openai_base_url'])
    key = html.escape(KEY_ENV)
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free AI Gateway — Help / Conexión</title>
<style>
:root{{--bg:#07111f;--p:#0f1a2f;--b:#1f355f;--t:#eaf2ff;--m:#9cb3d6;--a:#22c55e;--c:#06b6d4}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 system-ui,Segoe UI,Arial;background:linear-gradient(180deg,#081225,#050b16);color:var(--t)}}
.w{{max-width:1100px;margin:0 auto;padding:22px}}.card{{background:rgba(15,26,47,.92);border:1px solid var(--b);border-radius:16px;padding:16px;margin:12px 0}}
h1{{margin:0 0 6px;font-size:28px}}h2{{margin:0 0 8px;font-size:18px;color:#cfe2ff}}.m{{color:var(--m)}}code,pre{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
pre{{white-space:pre-wrap;word-break:break-word;background:#081120;border:1px solid var(--b);border-radius:12px;padding:12px;margin:8px 0;overflow:auto}}
code{{background:#081120;border:1px solid var(--b);padding:1px 6px;border-radius:6px}}.k{{display:inline-block;padding:3px 8px;border:1px solid #2a4a33;color:#86efac;background:#0a1d13;border-radius:999px;font-size:12px;margin-right:6px}}
a{{color:#7dd3fc}}.g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.warn{{border-color:#5b4a1f;background:rgba(60,40,10,.18)}} table{{width:100%;border-collapse:collapse}} td,th{{border-bottom:1px solid var(--b);padding:8px;text-align:left;vertical-align:top}} th{{color:#cfe2ff}}
</style></head><body><div class="w">
<h1>Free AI Gateway — Conexión</h1>
<p class="m">Endpoint OpenAI-compatible publicado. Usa <b>una sola API key del gateway</b>. Recomendado: variable de entorno <code>{key}</code>.</p>
<div class="card"><span class="k">Base URL</span> <code>{base}</code><br><span class="k">Modelo</span> <code>auto</code> (fallback, caché, compresión, FREE_ONLY)<br><span class="k">Auth</span> <code>Authorization: Bearer ${key}</code> (también <code>api-key</code>/<code>x-api-key</code>)</div>
<div class="g">
<div class="card"><h2>OpenCode</h2><pre>export {key}="TU_API_KEY_GATEWAY"
# En la configuración de proveedor OpenAI-compatible/custom:
# baseURL = {base}
# apiKey  = ${key}
# model   = auto</pre><p class="m">Usa el endpoint del gateway como proveedor compatible; no expongas claves upstream.</p></div>
<div class="card"><h2>Kimi Code / Kimi</h2><pre>export {key}="TU_API_KEY_GATEWAY"
# Configura cliente/harness OpenAI-compatible:
# base_url = {base}
# api_key  = ${key}
# model    = auto</pre><p class="m">Apunta al gateway; la clave es la del gateway. Moonshot/Kimi upstream solo si está configurado en el servidor y permitido por política/cuenta.</p></div>
<div class="card"><h2>DeepSeek harness</h2><pre>export {key}="TU_API_KEY_GATEWAY"
export OPENAI_BASE_URL="{base}"
export OPENAI_API_KEY="${key}"
# model=auto</pre><p class="m">Para harnesses OpenAI-compatible. Ajusta nombres de variables si el harness usa otras (p. ej. DEEPSEEK_API_KEY/base); el valor debe ser la API key del gateway.</p></div>
<div class="card"><h2>KiloCode</h2><pre># Proveedor: OpenAI Compatible / OpenAI API
Base URL: {base}
API Key:  ${key}   (valor de tu gateway)
Model:    auto</pre><p class="m">En terminal: <code>export {key}="..."</code> y referencia esa variable en tu config si el cliente la soporta.</p></div>
</div>
<div class="card"><h2>Prueba rápida</h2><pre>export {key}="TU_API_KEY_GATEWAY"
curl -sS {html.escape(d['public_base_url'])}/v1/chat/completions \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"model":"auto","messages":[{{"role":"user","content":"Hola"}}],"max_tokens":64,"temperature":0}}'</pre></div>
<div class="card warn"><h2>Notas reales</h2><p class="m"><b>Gratis/controlado ≠ ilimitado.</b> FREE_ONLY activo por política: solo fuentes/anónimos free-tier explícitos cuando aplica. Proveedores upstream imponen cuotas/rate limits/créditos/capacidad. <b>Rota la API key</b> si se expuso. No uses claves upstream en clientes.</p></div>
<div class="card"><h2>JSON de ayuda</h2><p class="m"><a href="/help.json">/help.json</a> · <a href="/v1/help">/v1/help</a> · <a href="/health">/health</a> · <a href="/v1/audit">/v1/audit</a> (auth)</p><pre>{j}</pre></div>
</div></body></html>'''
