# Progreso 2026-11-08: generación de proyecto saga vía KimiCode + ForthTrade IA

## Objetivo

Generar un proyecto temporal de **orquestador de transacciones distribuidas tipo saga** usando **KimiCode local** como cliente y **ForthTrade IA** (`https://ia.forthtrade.com/v1`, modelo `auto`) como proveedor de generación.

## Estado de KimiCode

- Binario: `~/.kimi-code/bin/kimi` versión `2.5.2`.
- Provider configurado: `openai` con `base_url=https://ia.forthtrade.com/v1` y alias `auto`.
- Prompt modes probados: `kimi -p "..." --output-format text`.
- La API key del gateway no se documenta ni se imprime (P0.6).

## Hallazgo: no era un deadlock

La primera ejecución parecía colgada porque:

- KimiCode envía el **razonamiento a stderr** y solo escribe la respuesta final a stdout al terminar.
- Con `--output-format text`, stdout permanece vacío durante toda la generación.
- La sesión `session_21e7176f-e8f0-4436-9695-d4bcc202fa06` fue cancelada externamente cuando el modelo ya estaba en la fase "Writing final code now"; stderr tenía ~144 KB de razonamiento.
- Los logs de sesión muestran múltiples `turnStep` y llamadas `POST /v1/chat/completions`.

## Causa raíz de los fallos posteriores

1. **Cuota free agotada:** OpenRouter `429 free-models-per-day`; LLM7 `429 Daily token quota exceeded`; Pollinations `1 reply every 45 seconds per IP`.
2. **Causa capturada con proxy local:** el error `Chat Completions provider returned invalid or omitted terminal usage` (`type=upstream_error`, `code=usage_missing`) lo emite el backend anónimo de Pollinations, no el gateway ni KimiCode. Se reproduce cuando el request incluye `reasoning_effort` (KimiCode lo agrega desde `turnStep 0.2`). `curl` sin ese campo recibe `200`, `usage` y `[DONE]`.
3. **Fix aplicado:** `PollinationsProvider._prepare` descarta `reasoning_effort` y `prompt_cache_key`; KimiCode local usa el alias `auto-nothink` (`capabilities = []`) para no enviar `reasoning_effort`. Ya no aparece `usage_missing`.
4. **Bloqueo restante:** Pollinations anónimo devuelve `completion_tokens=1500` y `finish_reason=length` incluso con default `CHAT_DEFAULT_MAX_TOKENS=4000`. El primer turno consume 1500 tokens en razonamiento/tool call; los siguientes vuelven vacíos (`APIEmptyResponseError` de KimiCode: “empty response ... finishReason=truncated”). Falta más cuota de salida, otro proveedor free o un agente/prompt más liviano. No hay proyecto generado ni tests todavía.
5. Bug de observabilidad: `router._record` llamaba `_metrics_obs.metrics.update_provider_stats`, pero `_metrics_obs` ya es el objeto `Metrics`. Antes estaba oculto por `except: pass`; ahora se corrigió a `_metrics_obs.update_provider_stats` y las métricas por proveedor vuelven a registrarse.

## Cambios aplicados para compatibilidad free-tier

- `POLLINATIONS_MIN_INTERVAL=46` (default): serializa llamadas a Pollinations para respetar ~1 respuesta/45s/IP.
- `FREE_TIER_MAX_WAIT=60`: espera máxima por spacing antes de devolver error honesto.
- Tests smoke fijan `POLLINATIONS_MIN_INTERVAL=0` para no alargar la suite.
- Verificación directa: dos requests streaming consecutivas → primera ~0s, segunda ~46s; ambas `200`, con bloque `usage` y `[DONE]`.
- Esta espera es deliberada: **gratis controlado ≠ ilimitado**; la latencia refleja el rate limit upstream.

## Ejecución actual

- Directorio temporal: `/tmp/forthtrade-saga-20261108-145004`; contiene solo `saga_demo/` vacío.
- Prompt: `/tmp/saga_prompt.txt` (Python 3.11+ stdlib, SQLite/WAL, saga/compensaciones/retries/idempotencia/DLQ/recovery/tests unittest).
- Runs en background con `timeout 2400`, stdout `/tmp/saga_run_out.txt`, stderr `/tmp/saga_run_err.txt`.
- Evidencia de throttling: journal con `free-tier throttle pollinations: waiting ...`; requests `POST /v1/chat/completions` `200` espaciadas ~46s.
- Evidencia capturada (proxy local 8010, headers `authorization` redactados):
  - `turnStep 0.1`: `200`, `usage`, `tool_calls`, `completion_tokens=1500`.
  - Con `reasoning_effort`: `200` + evento SSE de Pollinations `usage_missing` (sin `usage`/`[DONE]`).
  - Sin `reasoning_effort`: `200`, `usage`, `[DONE]`, pero `finish_reason=length` y contenido vacío; KimiCode reporta `APIEmptyResponseError`.
- Alias KimiCode `auto-nothink` agregado en `~/.kimi-code/config.toml` (config local, no versionada).
- Run detenido para no seguir consumiendo cuota en loop. Sesiones KimiCode en `~/.kimi-code/session_index.jsonl`; reanudar con `kimi -S <sessionId> -p "..."`.
- Aún **no hay proyecto generado ni tests ejecutados**; no afirmar lo contrario.

## Próximos pasos

1. Conseguir salida >1500 tokens: otra cuenta/proveedor free con cuota disponible, o un agente/prompt más pequeño que complete el proyecto en un solo turno.
2. Repetir generación, extraer bloques `### FILE:` con el parser de `app/project_gen.py` a un directorio temporal seguro.
3. Ejecutar `python -m unittest discover -s tests -v`; si falla, reanudar KimiCode con el error exacto.
4. Documentar evidencia final (archivos, tests, intentos de gateway) y limitaciones de cuota.

## Evidencia relacionada

- Commits de hardening del gateway: `b015f76`, `1f61355`, `61366e7`.
- Logs: `journalctl --user -u free-ai-gateway`, `~/.kimi-code/logs/kimi-code.log`.
- THROTTLE: mensajes `free-tier throttle pollinations: waiting ...` en el journal.

## Actualización 2026-11-08 22:20: proyecto completado

La generación se completó usando **KimiCode 2.5.2** como cliente del
**ForthTrade IA público** (`https://ia.forthtrade.com/v1`). El camino
`forthtrade/auto` funcionó para prompts cortos, pero el agente se quedó sin
salida por el límite de Pollinations y por `usage_missing`. Se añadieron alias
locales de KimiCode con backup de `~/.kimi-code/config.toml`; el modelo que
completó el código fue `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free` a
través del gateway público. No se imprimieron ni commitearon claves.

Proyecto final: `examples/forthtrade-saga/`.

| Archivo | Líneas | Contenido |
|---|---:|---|
| `saga_core.py` | 234 | Núcleo SAGA, SQLite/WAL, idempotencia, retries, compensaciones, DLQ, recovery, concurrencia |
| `saga_cli.py` | 120 | CLI de 9 escenarios, `audit`, `dlq`, `recover` |
| `tests/test_saga.py` | 212 | 11 tests unittest |
| `README.md` | 107 | Arquitectura, estados, comandos y límites |

Verificación ejecutada desde `examples/forthtrade-saga`:

- `python3 -m unittest discover -s tests -v`: **11/11 OK**.
- Los 9 escenarios `demo` salieron con código 0: happy, payment_fail,
  inventory_fail, shipping_fail, compensation_fail, retry_success,
  crash_recovery, duplicate, concurrent.
- `crash_recovery`: primera ejecución **RUNNING**, luego
  `recover(force=True)` → **COMPLETED**, sin duplicar el pago.
- `duplicate`: mismo `request_id` dos veces → **3 efectos** totales, no 6.
- `concurrent`: 8 sagas con 4 workers → todas **COMPLETED**.
- `audit`, `dlq` y `recover` ejecutados con exit 0.

La autoría del código es de ForthTrade IA/KimiCode; el operador solo orquestó
prompts, ejecutó tests y devolvió errores concretos para la depuración. Los
datos de runtime y los logs de orquestación quedaron fuera del repositorio.
El proyecto es una simulación local en proceso; no sustituye microservicios
reales, red distribuida, TLS/auth ni exactly-once de red.
