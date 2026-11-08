# 2026-11-08: fallback local Qwen3.5-9B (Ollama) sobre NCM-725M

## Decisión

Se reemplaza como fallback local principal el NCM-Instruct-725M por
**Qwen3.5-9B Q4_K_M** servido por Ollama. Motivo: el NCM de 725M es un modelo
de hobby con contexto 128 y hechos débiles; Qwen3.5-9B es un instruct general
Apache-2.0 que entra en 8 GB de VRAM en Q4_K_M (6.6 GB) y conserva margen para
contexto. NCM queda como proveedor experimental opt-in, no activo por defecto.

## Hardware y configuración

- GPU: RTX 3070 Laptop, 8 GB VRAM; RAM 15 GB; disco libre >300 GB.
- Ollama: **0.40.15** (servicio `ollama.service`), loopback `127.0.0.1:11434`.
- `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_NUM_PARALLEL=1`,
  `OLLAMA_MAX_LOADED_MODELS=1` para evitar thrashing en 8 GB.
- Modelo: `qwen3.5:9b-q4_K_M` (6.6 GB, Apache-2.0).

## Integración

- Proveedor `local-ollama` (`app/providers/configured.py`), base
  `http://127.0.0.1:11434/v1`, modelo `local-ollama/qwen3.5:9b-q4_K_M`.
- `LOCAL_OLLAMA_ENABLED=1`, `LOCAL_OLLAMA_BASE_URL`, `LOCAL_OLLAMA_MODEL`.
- `FREE_ONLY`: proveedor local gratuito (sin costo upstream).
- Orden de `auto`: remotos gratuitos → `local-ollama` → `ncm` (si está
  habilitado) → segundos modelos remotos. Con `max_attempts=4`, Qwen entra en
  el 4.º intento; NCM no compite por VRAM porque está deshabilitado.
- El gateway no expone claves upstream; Ollama es loopback.

## Evidencia real (2026-11-08)

- `ollama list`: `qwen3.5:9b-q4_K_M`, **6.6 GB**.
- `ollama ps`: **5.7 GB**, **100% GPU**, contexto **8192**, runner `llamacpp`,
  keep-alive **29 min**.
- Benchmark `/api/chat` (RTX 3070, 8192 ctx):
  - carga inicial en frío: **29.4 s**; carga en caliente: **4.2 s**.
  - generación: **62–63 tok/s**.
  - matemática: `7×8` → `56` (3.9 s con thinking; **0.23 s con think:false**).
  - código: `reverse_string` correcto (6.2 s thinking; **0.52 s think:false**).
  - chat: explicación del cielo en 3 bullets, coherente (15.9 s thinking).
- Gateway → `local-ollama/qwen3.5:9b-q4_K_M` (`cache:false`):
  - `7×8` → `56` en **0.23 s**.
  - código → función correcta en **0.52 s**.
  - `auto` + `gateway.providers=["local-ollama"]` → `9×9` = `81`, selected local.
  - streaming SSE token por token, sin razonamiento, con `[DONE]`.
  - `auto` normal sigue eligiendo `pollinations` primero.
- `gateway.local_min_tokens`, `gateway.think`, `gateway.num_ctx` visibles en metadata.

## Hallazgo clave

El shim OpenAI de Ollama **ignora `think:false`** y el modelo puede gastar todo
el presupuesto en razonamiento (`content` vacío, `finish=length`). El endpoint
nativo `/api/chat` **sí respeta `think:false`**. Por eso `OllamaLocalProvider`
usa `/api/chat` nativo, convierte a OpenAI y emite SSE; con `think:false`
responde directo y rápido. `LOCAL_OLLAMA_MIN_TOKENS=512` queda como red de
seguridad.

## Límites honestos

- 6.6 GB de pesos + KV cache en 8 GB es ajustado; si Ollama offloadea capas a
  CPU, la latencia sube. Se mide y se reporta; no se asume GPU completa.
- Qwen3.5-9B no es un modelo frontier; los benchmarks de terceros son
  orientativos, no una garantía en este hardware.
- NCM-Instruct-725M sigue siendo CC BY-NC-SA 4.0 (no comercial) y no debe
  ejecutarse a la vez que Qwen 9B en 8 GB.
