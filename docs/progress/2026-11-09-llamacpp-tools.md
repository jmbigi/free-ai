# 2026-11-09 — Herramientas locales y backend opcional llama-cpp-python

## Alcance

Se integraron dos mejoras verificables en el gateway:

1. **Tool calling nativo de Ollama** (`local-ollama`): preserva el historial
   `assistant.tool_calls` / `tool`, convierte las llamadas nativas al contrato
   OpenAI y emite `finish_reason="tool_calls"` también en streaming.
2. **Backend opcional `local-llamacpp`**: habla con el servidor
   OpenAI-compatible de `llama-cpp-python`, parsea las llamadas XML de
   Qwen3-Coder (`<tool_call><function=...>`) a `tool_calls` OpenAI y convierte
   el historial de vuelta al formato que espera el template GGUF.

El backend llama-cpp-python es **opt-in** (`LOCAL_LLAMACPP_ENABLED=0` por
defecto). Ollama sigue siendo el motor local principal.

## Implementación

- `app/providers/ollama_tools.py`
  - `to_ollama_messages`: OpenAI → Ollama nativo, incluyendo `tool_name`.
  - `normalize_tool_calls`: Ollama/OpenAI → OpenAI `tool_calls`.
  - `build_completion` / `stream_delta`: respuestas y deltas SSE con tools.
- `app/providers/llamacpp_tools.py`
  - Parser XML/JSON de Qwen3-Coder.
  - `to_llamacpp_messages`: serializa `assistant.tool_calls` como XML dentro de
    `content` antes de enviarlo al servidor. Es necesario porque el validador
    FastAPI de llama-cpp-python acepta `arguments` como string, pero el template
    GGUF lo consume como mapping (`|items`); enviar XML evita ese choque.
  - `tool_calls_to_qwen_xml` y normalización de argumentos.
- `app/providers/configured.py`
  - `OllamaLocalProvider`: tools en `chat` y `stream_chat`.
  - `LlamaCppLocalProvider`: tools, timeout configurable y SSE bufferizado para
    no filtrar XML al cliente.
- `app/router.py`, `app/config.py`, `app/main.py`: registro, política free,
  catálogo y orden de fallback (`local-llamacpp` después de Ollama y antes de
  NCM).
- `deploy/llamacpp-server.sh` y `deploy/free-ai-llamacpp.service`: arranque
  opcional, sin activación automática. El operador decide cuándo iniciarlo.

## Pruebas unitarias

```bash
.venv/bin/python -m unittest \
  tests_ollama_tools_unit.py \
  tests_llamacpp_tools_unit.py \
  tests_router_unit.py \
  tests_ncm_benchmark_unit.py \
  tests_ncm_response_unit.py
```

Resultado: **54 tests OK, 1 skipped** (incluye los tests previos de router/NCM).

Prueba directa del gateway con `local-llamacpp`:

- Primera llamada con `write_file`: HTTP 200, `finish_reason="tool_calls"`,
  argumentos válidos, 23.59 s.
- Segunda llamada con `role="tool"`: HTTP 200, contenido `hecho`; el historial
  de herramientas sobrevivió al round-trip.
- KimiCode con `free-ai-local/llamacpp-qwen3-coder`: creó
  `llamacpp_probe.txt` mediante herramientas. Contenido observado: `ok.` (el
  modelo añadió el punto; no se fuerza una normalización silenciosa).

## Benchmark real (RTX 3070 Laptop 8 GB, Ryzen 9 5900HX)

Modelo: `qwen3-coder-opt:latest`, Qwen3-MoE 30.5B, Q4_K_M, contexto 16384.

| Backend | Configuración | Evaluación | Tokens/s |
|---|---|---:|---:|
| Ollama 0.40.15 | modelo cargado por Ollama, 97 % GPU reportado | 128 tokens en 5.85 s | **21.88** |
| llama-cpp-python 0.3.36 | 16 capas GPU, KV Q8_0 | 128 tokens en 17.38 s | **7.36** |
| llama-cpp-python 0.3.36 | 12 capas GPU, KV Q8_0 | 128 tokens en 18.46 s | **6.93** |

Carga: Ollama ~22.5 s; llama-cpp-python ~16.6 s. En este hardware el backend
Python es más lento porque solo puede descargar parte de las capas del MoE a la
GPU (8 GB); Ollama aplica su propia optimización de serving. Por eso
`local-llamacpp` **no reemplaza** a Ollama ni se activa por defecto. Es útil para
modelos que caben completos en VRAM, para comparar y como respaldo explícito.

Nota técnica: los wheels CUDA precompilados de llama-cpp-python 0.3.36 incluían
`libggml-cpu` con instrucciones AVX-512; en este Ryzen solo hay AVX2 y el proceso
terminaba con `SIGILL`. Se reemplazó únicamente la librería CPU por una
compilación AVX2 (`GGML_AVX512=OFF`, `GGML_NATIVE=OFF`) conservando el backend
CUDA del wheel. El procedimiento no se versiona como dependencia obligatoria.

## Matriz KimiCode

| Cliente/modelo | Gateway | Tarea | Resultado |
|---|---|---|---|
| KimiCode + `free-ai-local/qwen3-coder-opt` (Ollama) | local | crear archivo con tools | **OK** |
| KimiCode + `free-ai-local/llamacpp-qwen3-coder` | local | crear archivo con tools | **OK** (`ok.`) |
| KimiCode + `free-ai-local/nemotron-free` | cloud free | SAGA desde cero, 5 tests | **5/5 OK** |
| KimiCode + `free-ai-local/qwen3-coder-opt` | local | SAGA desde cero / corrección | **No logrado**: la primera pasada modificó los tests (se invalidó); la segunda conservó el hash del test pero entró en bucle y agotó el timeout. Se reporta como limitación real, no como éxito. |

El test SAGA cloud está en `/tmp/user/1000/opencode/kimi-saga-bench-nemotron` y
el proyecto local de referencia en
`/tmp/user/1000/opencode/forthtrade-saga-local-20261108-222754` (fuera del repo).
El ejemplo cloud versionado sigue en `examples/forthtrade-saga/`.

## Límites honestos

- **Gratis controlado ≠ ilimitado**: Nemotron/OpenRouter y el resto de fuentes
  free tienen cuotas, rate limits, créditos y capacidad variable.
- El backend llama-cpp-python no garantiza tool calling en cualquier GGUF; el
  parser está orientado a Qwen3-Coder y formatos XML/JSON compatibles.
- El servidor llama-cpp-python no se inicia ni se habilita automáticamente. El
  programador controla su activación.
- La prueba local SAGA no se declara superada; el modelo local de 30B en 8 GB
  con KimiCode mostró bucles y la primera ejecución tocó los tests.
