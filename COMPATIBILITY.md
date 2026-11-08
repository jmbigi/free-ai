# Compatibilidad de clientes (API key simple)

Base URLs:
- `http://HOST:8000/v1`
- `http://HOST:8000/openai/v1`
- `http://HOST:8000/api/v1`

Auth (usa la misma `API_KEY` del `.env` del gateway):
- `Authorization: Bearer <API_KEY>` (OpenAI/KiloCode/OpenCode/DeepSeek harness)
- `api-key: <API_KEY>`
- `x-api-key: <API_KEY>`
- `?api_key=<API_KEY>` o `?key=<API_KEY>` (solo pruebas)

## KiloCode / OpenCode / clientes OpenAI
- Base URL: `http://HOST:8000/v1`
- API key: `<API_KEY>`
- Modelo recomendado: `auto` (fallback entre APIs remotas gratuitas/configuradas)
- Caché: automática para `temperature=0` (o `cache:true` en el body). `no_cache:true` o `cache:false` la desactiva.
- Compresión de contexto: automática cuando el historial supera `CONTEXT_MAX_CHARS`; también `compress_context:true`.

## KimiCode local
- Provider `free-ai-local`: `http://127.0.0.1:8000/v1`, `api_key_env=FT_AI_API_KEY`, modelo `free-ai-local/auto`.
- Verificado con KimiCode 2.5.2 (`kimi doctor` OK; prompt `ok`, exit 0).
- `auto` usa primero proveedores remotos gratuitos; el NCM LM1B-large local es explícito y no está en `auto`.

## DeepSeek harness / clientes con `prompt` o `input`
- `POST /v1/chat/completions` acepta `messages`, `prompt`, `input` y `max_completion_tokens`.
- Alias de rutas: `/chat/completions`, `/openai/v1/chat/completions`, `/api/v1/chat/completions`.

## Streaming
- `stream:true` en `/v1/chat/completions` (SSE, `data: ...`, `[DONE]`). La caché de respuesta completa aplica a respuestas no-stream.
- Timeout de lectura acotado: un upstream que deja de enviar chunks aborta en vez de colgar el stream.
- Si un stream ya emitió salida parcial y falla, no se reintenta con otro proveedor (evita mezclar respuestas).

## Fallback local (Qwen3.5-9B + NCM experimental)
- **Principal:** `local-ollama/qwen3.5:9b-q4_K_M` (loopback `http://127.0.0.1:11434/v1`, Ollama 0.40.15). 6.6 GB Q4_K_M, Apache-2.0, contexto 8192.
- **Último recurso:** `ncm/ncm-instruct-725m` (loopback 11435; 725M, 128 tokens, CC BY-NC-SA 4.0, opt-in). No ejecutar ambos en 8 GB de VRAM.
- **NCM oficial explícito:** `ncm-lm1b/ncm-lm1b-large` (loopback 11436; 725M, unconditional, 128 tokens fijos, ignora el prompt). No se usa en `auto`.
- `auto`: remotos gratuitos → `local-ollama` → `ncm` → segundos modelos remotos.
- NCM metadata: `gateway.thinker` (intención, confianza, validez, notas) y `gateway.math_guard`.

## Anti-bloqueo / anti-ciclos
- Cada request tiene un presupuesto (`REQUEST_BUDGET`, 45s por defecto). Ningún intento ni espera de rate limit puede excederlo.
- Errores 401/403 (clave/cuenta) y 402/429 (cuota/rate limit) abren un **circuit breaker por proveedor**: se saltan todos sus modelos, no solo el que falló.
- Errores 400/422 de request inválido son **terminales**: no se reintentan en otros proveedores.
- Se respeta `Retry-After` (segundos o HTTP-date) y se devuelve en la respuesta del gateway cuando aplica.
- Estado visible en `GET /v1/status` → `runtime.provider_breakers` y `runtime.cooldowns`.

## Thinker (jmbigi/thinker real)
- `POST /v1/think`: `{"prompt","provider":"gateway|mock","model":"auto","max_steps":7,"use_tot":false}`.
- `POST /v1/verify`: `{"claim":"...","mode":"strict"}` o `{"response_text":"...","mode":"query"}`.
- Requiere `THINKER_ENABLED=1` y `thinker.service` en `127.0.0.1:11437`.
- `provider="mock"` se marca `simulated=true`; sin evidencia, `/v1/verify` devuelve `not_addressed` (no inventa `supported`).

## Endpoints operativos
- `GET /health`, `GET /v1/models`, `GET /v1/providers`
- `POST /v1/chat/completions`
- `GET /v1/cache`, `POST /v1/cache/clear`

## Limitación real
No existe inferencia remota avanzada verdaderamente ilimitada y gratis sin restricciones. Los proveedores gratuitos/remotos aplican cuotas, rate limits, créditos o condiciones. Este gateway agrega cuentas/fuentes gratuitas disponibles y usa `auto` para maximizar disponibilidad.
