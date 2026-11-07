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

## DeepSeek harness / clientes con `prompt` o `input`
- `POST /v1/chat/completions` acepta `messages`, `prompt`, `input` y `max_completion_tokens`.
- Alias de rutas: `/chat/completions`, `/openai/v1/chat/completions`, `/api/v1/chat/completions`.

## Streaming
- `stream:true` en `/v1/chat/completions` (SSE, `data: ...`, `[DONE]`). La caché de respuesta completa aplica a respuestas no-stream.

## Endpoints operativos
- `GET /health`, `GET /v1/models`, `GET /v1/providers`
- `POST /v1/chat/completions`
- `GET /v1/cache`, `POST /v1/cache/clear`

## Limitación real
No existe inferencia remota avanzada verdaderamente ilimitada y gratis sin restricciones. Los proveedores gratuitos/remotos aplican cuotas, rate limits, créditos o condiciones. Este gateway agrega cuentas/fuentes gratuitas disponibles y usa `auto` para maximizar disponibilidad.
