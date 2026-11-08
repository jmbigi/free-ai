# Free AI Gateway (v2.3.0)

Gateway **OpenAI-compatible**, público y robusto, con **una sola API key** del gateway (`FT_AI_API_KEY` / `API_KEY` en `.env`). Agrega proveedores gratuitos/free-tier configurables, usa `model="auto"` con fallback inteligente, caché, compresión de contexto, control **FREE_ONLY** y observabilidad.

- **Público:** `https://ia.forthtrade.com` · Base API: `https://ia.forthtrade.com/v1`
- **Ayuda/conexión:** `https://ia.forthtrade.com/help` · JSON: `https://ia.forthtrade.com/help.json`

## Inicio rápido
```bash
export FT_AI_API_KEY="TU_API_KEY_GATEWAY"
curl -sS https://ia.forthtrade.com/v1/chat/completions \
  -H "Authorization: Bearer $FT_AI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hola"}],"max_tokens":64,"temperature":0}'
```

## Clientes (OpenAI-compatible)
- **OpenCode:** base URL `https://ia.forthtrade.com/v1`, API key `$FT_AI_API_KEY`, modelo `auto`.
- **Kimi Code / Kimi (cliente compatible):** base URL `https://ia.forthtrade.com/v1`, API key `$FT_AI_API_KEY`, modelo `auto`.
- **DeepSeek harness:** `OPENAI_BASE_URL=https://ia.forthtrade.com/v1`, `OPENAI_API_KEY=$FT_AI_API_KEY` (o variables del harness apuntando al gateway), modelo `auto`.
- **KiloCode:** OpenAI Compatible → Base URL `https://ia.forthtrade.com/v1`, API Key `$FT_AI_API_KEY`, Model `auto`.

## Endpoints
- `GET /health`, `GET /readyz` — sondeos rápidos.
- `GET /help`, `/help.json`, `/v1/help` — guía de conexión.
- `GET /v1/models`, `/v1/providers` — catálogo/estado (auth).
- `POST /v1/chat/completions` — chat OpenAI-compatible (auth).
- `POST /v1/responses` — compatibilidad básica Responses API (auth).
- `GET /v1/metrics`, `/v1/audit`, `/v1/status`, `/v1/free`, `/v1/cache`, `/v1/telemetry`, `/v1/debug`, `/v1/connections`, `/v1/tools` — observabilidad/auditoría (auth). No exponen IPs de clientes.

## Auth (gateway)
Una sola clave: `.env` `API_KEY` o `FT_AI_API_KEY`. Acepta `Authorization: Bearer`, `api-key`, `x-api-key`, `?api_key/key`. **No** enviar claves upstream a clientes. Rotar si se expone.

## Capacidades
OpenAI-compatible, aliases (`messages/prompt/input`, `max_tokens/max_completion_tokens/max_output_tokens`), SSE streaming, `x-request-id`/`x-gateway-version`, errores normalizados, guardrail de tamaño, caché de respuestas, compresión de contexto, routing inteligente con fallback/cooldowns, control `FREE_ONLY`.

## Agregar proveedores/cuentas
En `.env` (gitignored): `OPENROUTER_API_KEY`, `HUGGINGFACE_API_KEY`/`HUGGING_FACE_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, Cloudflare/Mistral/SambaNova/Cerebras/Together/Cohere/DeepSeek/Moonshot/OpenCode/custom OpenAI-compatible. Reinicio/recarga según caso; `GET /v1/providers` para estado real.

## Operación local
```bash
cd /home/admin/free-ai && ./run.sh   # 127.0.0.1:8000 por defecto (detrás del proxy)
# o systemd --user: deploy/free-ai-gateway.service
.venv/bin/python tests_smoke.py
```
No exponer `0.0.0.0:8000` a Internet: bypassa HTTPS y la redacción de logs. Público solo por `https://ia.forthtrade.com` (Apache).

## Referencias y avances
- `docs/references/ncm-2610.14162.md` — resumen verificable del paper NCM (arXiv:2610.14162v1), límites y relevancia. Referencia externa, no dependencia.
- `docs/progress/2026-11-08-saga-generation.md` — estado real de la generación del proyecto saga vía KimiCode + ForthTrade IA, diagnóstico de throttling free-tier y próximos pasos.

## Limitación real (obligatoria)
**Gratis/controlado ≠ ilimitado.** `FREE_ONLY` prioriza candidatos free-tier/anónimos explícitos, pero proveedores upstream imponen cuotas, rate limits, créditos, términos o capacidad variable. El gateway maximiza disponibilidad; **no garantiza inferencia remota avanzada gratuita ilimitada**. Reportar estado con evidencia (`/v1/audit`, `/v1/metrics`, `attempts`).

## Programación autónoma
Ver `AGENT_PROGRAMMING.md` para conexión OpenAI-compatible (KiloCode/OpenCode/Kimi/DeepSeek harness/SDK), tools, `/v1/responses`, `/v1/search`, `/v1/decision` y límites FREE_ONLY.
- `POST /v1/projects/generate`: generación de proyectos temporales por ForthTrade IA (extrae `### FILE`, evidencia, borrado temp por defecto; respeta FREE_ONLY/rate limits).
