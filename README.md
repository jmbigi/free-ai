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
- **KimiCode local:** provider `free-ai-local`, base URL `http://127.0.0.1:8000/v1`, API key `$FT_AI_API_KEY`, modelo `free-ai-local/auto`. Requiere el gateway local activo; ver `docs/progress/2026-11-08-kimicode-local.md`.
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

## Robustez de fallback (anti-bloqueo / anti-ciclos)
- **Presupuesto por request** (`REQUEST_BUDGET`, 45s): ninguna llamada ni espera de rate limit puede excederlo; si no cabe, se falla rápido con `Retry-After` en vez de dormir y fallar después.
- **Circuit breaker por proveedor**: un 401/403 (clave/cuenta) o 402/429 (cuota/rate limit) abre el circuito y salta **todos** los modelos de ese proveedor; no se recorren 6 rutas condenadas a fallar.
- **Clasificación de errores**: request inválido (400/422) = terminal (se corta de inmediato); modelo inexistente = se prueba otro modelo; 5xx/timeout = transitorio con umbral de breaker.
- **`Retry-After` real**: se parsea de los headers upstream y se propaga al cliente (header y metadata).
- **Streaming acotado**: timeout de lectura por chunk; si ya hubo salida parcial no se reintenta para no mezclar respuestas.
- Basado en prácticas verificables: [AWS exponential backoff + jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/), [Google SRE: handling overload](https://sre.google/sre-book/handling-overload/), [Azure circuit breaker](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker) y [RFC 9110 §10.2.3 Retry-After](https://www.rfc-editor.org/rfc/rfc9110#section-10.2.3).
- Estado real: `GET /v1/status` → `runtime.provider_breakers`, `runtime.cooldowns`.

## Fallback local (Qwen3.5-9B + NCM experimental)
- **Principal:** `local-ollama/qwen3.5:9b-q4_K_M` en `http://127.0.0.1:11434/v1` (servicio `ollama.service`). 6.6 GB Q4_K_M, Apache-2.0, contexto Ollama 8192. Usa `/api/chat` nativo con `think:false` (el shim OpenAI ignora ese flag), 100% GPU y ~62 tok/s.
- **Último recurso:** `ncm/ncm-instruct-725m` (725M, contexto 128, CC BY-NC-SA 4.0, opt-in). **No ejecutar ambos en 8 GB de VRAM.**
- **NCM oficial explícito:** `ncm-lm1b/ncm-lm1b-large` (725M, unconditional, 128 tokens fijos, ignora el prompt; servicio `ncm-lm1b.service`). No se enruta en `auto`; es solo para experimentación explícita.
- `auto` ordena: remotos gratuitos → `local-ollama` → `ncm` (si está activo) → segundos modelos remotos. Con `max_attempts=4`, Qwen entra en el 4.º intento.
- Variables: `LOCAL_OLLAMA_ENABLED=1`, `LOCAL_OLLAMA_BASE_URL`, `LOCAL_OLLAMA_MODEL`; NCM con `NCM_LOCAL_ENABLED=0` por defecto.
- NCM conserva la capa `thinker-lite` (clean-room, inspirada en [jmbigi/thinker](https://github.com/jmbigi/thinker), GPL-3.0-only): matemática determinista, best-of-3, validación y reparación honesta.
- Evidencia: `docs/progress/2026-11-08-qwen-local-fallback.md` y `docs/progress/2026-11-08-ncm-local-fallback.md`.

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
