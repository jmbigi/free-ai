# Comparación Nemotron Cloud vs Modelos Locales + Plan de Mejoras

## 1. Benchmark Comparativo (2026-11-09, RTX 3070 Laptop 8GB)

| Métrica | **Nemotron 3 Ultra (Cloud :free)** | **NCM-Instruct 725M (Local)** | **Ollama qwen3-coder-opt 30.5B (Local)** | **llama-cpp-python qwen3-coder-opt (Local)** |
|---|---:|---:|---:|---:|
| **Latencia (math simple)** | 3.35 s (1.96 s upstream) | **1.14 s** (0.9 s upstream) | 29.59 s | ~23-25 s |
| **Tokens/s (eval)** | ~50-100 (est.) | **~380-680** (batch 1-4) | ~22 | ~7 |
| **Calidad respuesta** | Natural, conversacional | Determinista, estructurada | Verbosa, conversacional | Verbosa, conversacional |
| **Math guard** | ❌ No nativo | ✅ **Determinista** (thinker-lite) | ❌ LLM-based | ❌ LLM-based |
| **Contexto** | 128k+ | **128 fijo** | 16k (config) | 16k (config) |
| **Streaming real** | ✅ | ❌ Bufferizado (NCM limit) | ✅ | ✅ (pero tools bufferizado) |
| **Tool calling** | ✅ OpenAI nativo | ❌ No | ✅ Ollama nativo | ✅ Via XML parser |
| **Cuota/Rate limit** | **Sí** (429 daily, 402 cooldown) | **No** (100% local) | **No** | **No** |
| **VRAM** | N/A (cloud) | **3.4 GB** | ~7-8 GB (97% GPU) | 4.9 GB (12-16 layers) |
| **Licencia** | NVIDIA (comercial) | **CC BY-NC-SA 4.0** | Apache 2.0 (Qwen) | Apache 2.0 (llama.cpp) |
| **Costo operativo** | $0 (free tier, cuotas) | $0 (hardware own) | $0 (hardware own) | $0 (hardware own) |

---

## 2. Análisis de Fortalezas/Debilidades

### Nemotron 3 Ultra (Cloud :free)
**Fortalezas:**
- Calidad conversacional superior
- Tool calling nativo OpenAI
- Contexto masivo (128k+)
- Razonamiento complejo (SAGA 5/5 desde cero)

**Debilidades:**
- **Cuotas impredecibles** (429 free-models-per-day, 402 cooldown 45s/IP)
- Latencia de red variable
- Dependencia de terceros (OpenRouter/NVIDIA)
- No math guard determinista

### NCM-Instruct 725M (Local + Thinker-lite)
**Fortalezas:**
- **Latencia mínima** (1.14 s total, ~0.9 s inferencia)
- **Math guard determinista** 100% fiable
- Thinker-lite metadata completa (intent, validation, repair)
- Sin cuotas, 100% offline
- Batch 1-4 nativo (380-680 tok/s)

**Debilidades:**
- Contexto **128 tokens fijo** (hard limit)
- **No streaming real** (bufferizado)
- No tool calling
- Licencia **CC BY-NC-SA 4.0** (no comercial)
- Calidad conversacional limitada

### Ollama qwen3-coder-opt 30.5B (Local)
**Fortalezas:**
- Tool calling nativo (Ollama)
- Contexto 16k configurable
- Calidad código superior
- Streaming real

**Debilidades:**
- **Lento** (29.6 s para math simple)
- Sin math guard determinista
- VRAM límite (8 GB → solo 97% GPU reportado, OOM risk)
- No batch nativo

---

## 3. Mejoras Planificadas por Categoría

### 3.1 API Local (`/v1/*` endpoints)

| Mejora | Archivo | Prioridad |
|---|---|---|
| **Unified model registry** con capacidades dinámicas | `app/router.py`, `app/providers/configured.py` | Alta |
| **Parameter validation estricta** (Pydantic v2) | `app/providers/base.py`, `app/main.py` | Alta |
| **Structured logging** con correlation IDs | `app/logging.py`, `app/main.py` | Media |
| **OpenAPI/Swagger auto-generado** | `app/main.py` (FastAPI) | Media |
| **Rate limiting por cliente** (token bucket) | `app/auth.py`, middleware | Alta |
| **Request/response compression** (gzip/zstd) | `app/main.py` middleware | Baja |

### 3.2 API Remota / Cloud Providers

| Mejora | Proveedor | Prioridad |
|---|---|---|
| **OpenRouter model discovery cache** (TTL 1h) | `OpenRouterProvider.list_models()` | Alta |
| **Nemotron-specific parameters** (`reasoning_effort`, `reasoning_tokens`) | `NvidiaProvider`, `OpenRouterProvider` | Alta |
| **Streaming timeout adaptativo** por proveedor | `OpenAICompatProvider.stream_chat()` | Media |
| **Fallback geo-distribuido** (múltiples endpoints) | `router.py` | Baja |
| **Cost tracking** por request (tokens × $/M) | `router.py`, `execute_with_fallback()` | Media |

### 3.3 Tools & Functions

| Mejora | Estado Actual | Target |
|---|---|---|
| **Function calling schema validation** (JSON Schema draft-07) | Parcial (OpenAI compat) | Completo con `jsonschema` lib |
| **Parallel tool calls** (`parallel_tool_calls=true`) | Ollama ✅, llama-cpp ⚠️, NCM ❌ | Unificado |
| **Tool result streaming** (progressive) | No | Sí (SSE deltas) |
| **MCP (Model Context Protocol) server** | No | **Nuevo** (ver 3.7) |
| **Built-in tools** (web_search, code_exec, file_ops) | `web_search` básico | Extender |

### 3.4 MCP (Model Context Protocol)

```python
# Nuevo: app/mcp/server.py
class MCPServer:
    """MCP server for gateway tools/resources."""
    def __init__(self):
        self.tools = {
            "web_search": WebSearchTool(),
            "code_exec": CodeExecTool(sandbox=True),
            "file_read": FileReadTool(root="/safe/path"),
            "file_write": FileWriteTool(root="/safe/path"),
            "kb_query": KnowledgeBaseTool(),
        }
        self.resources = {
            "docs://api": APIDocsResource(),
            "docs://models": ModelsResource(),
        }

# Endpoints:
# GET  /mcp/tools/list
# POST /mcp/tools/call
# GET  /mcp/resources/list
# POST /mcp/resources/read
```

**Integración:**
- KimiCode/OpenCode/DeepSeek harness → `mcp://gateway` transport
- Gateway expone tools locales + remotos unificados
- Auth via gateway API key

### 3.5 NCM Mejoras

| Mejora | Descripción | Archivos |
|---|---|---|
| **NCM-Instruct streaming real** | Modificar `ncm_server.py` para yield por token (requiere cambio en `sample()`) | `local/ncm/instruct/.../ncm_server.py` |
| **Context extension** (sliding window >128) | Sliding window + summary compression | `app/ncm/thinker_lite.py`, `ncm_server.py` |
| **Thinkerspecialization** | Sub-classes: `MathThinker`, `CodeThinker`, `FactThinker` | `app/ncm/thinker_lite.py` |
| **Batch inference API** | `POST /v1/ncm/batch` con `n=1..4` | `ncm_server.py`, `router.py` |
| **Quantization INT4/INT8** | `bitsandbytes` / `ggml` quantization para 725M | `local/ncm/.../quantize.py` |

### 3.6 Parámetros y Configuración

```python
# app/config.py - nuevos parámetros
class SettingsProxy:
    # Model parameters (per-provider override)
    MODEL_PARAMS: dict = {
        "nemotron-3-ultra": {"reasoning_effort": "high", "max_completion_tokens": 8192},
        "qwen3-coder-opt": {"think": False, "num_ctx": 16384},
        "ncm-instruct-725m": {"n": 3, "temperature": 0.3, "top_p": 0.9},
    }
    
    # Quantization profiles
    QUANT_PROFILES = {
        "q4_k_m": {"gguf": "Q4_K_M", "vrma_gb": 7.5},
        "q8_0": {"gguf": "Q8_0", "vrma_gb": 14.2},
        "int4": {"bits": 4, "group_size": 128},
        "int8": {"bits": 8},
    }
    
    # MCP
    MCP_ENABLED: bool = False
    MCP_TRANSPORT: str = "stdio"  # stdio | sse | ws
    MCP_TOOLS_ROOT: str = "/tmp/mcp-tools"
```

### 3.7 Cuantificación (Quantization)

| Modelo | Actual | Target | Herramienta |
|---|---|---|---|
| qwen3-coder-opt 30.5B | Q4_K_M (18 GB) | **Q3_K_M (14 GB)**, Q2_K (11 GB) | `llama-quantize`, `llama.cpp` |
| NCM-Instruct 725M | FP16 (3.4 GB VRAM) | **INT4 (1.1 GB)**, INT8 (2.0 GB) | `bitsandbytes`, `ggml` |
| NCM LM1B 725M | FP16 | **INT4/INT8** | Same |
| Nemotron (cloud) | N/A | N/A | N/A |

**Pipeline automatizado:**
```bash
# deploy/quantize-models.sh
#!/bin/bash
set -euo pipefail
MODEL=$1
TARGET_Q=$2  # q3_k_m, q2_k, int4, int8
./llama-quantize $MODEL $MODEL.$TARGET_Q.gguf $TARGET_Q
```

### 3.8 Python / Code Quality

| Mejora | Herramienta | Estado |
|---|---|---|
| **Type hints completos** (pyright strict) | `pyright`, `mypy` | Parcial |
| **Async throughout** (no sync blockers) | `asyncio`, `httpx` | ✅ Mayoría |
| **Structured config** (Pydantic Settings v2) | `pydantic-settings` | Parcial |
| **Dependency injection** (providers) | `fastapi.Depends` | ✅ |
| **Observability** (OpenTelemetry) | `opentelemetry-instrument` | Básico |
| **Property-based testing** | `hypothesis` | No |
| **Mutation testing** | `mutmut` | No |

---

## 4. Roadmap de Implementación

### Sprint 1 (Semana 1-2): API & Tools Core
- [ ] Unified model registry + capabilities
- [ ] MCP server básico (tools: web_search, file_ops)
- [ ] Parameter validation Pydantic v2
- [ ] OpenAPI spec auto-generated

### Sprint 2 (Semana 3-4): NCM & Local Models
- [ ] NCM-Instruct INT4 quantization
- [ ] Thinker-lite specialization (Math/Code/Fact)
- [ ] Batch inference API
- [ ] Sliding window context (soft >128)

### Sprint 3 (Semana 5-6): Cloud & Observability
- [ ] OpenRouter model discovery cache
- [ ] Nemotron reasoning parameters
- [ ] Cost tracking per request
- [ ] OpenTelemetry + Prometheus metrics

### Sprint 4 (Semana 7-8): MCP & Integration
- [ ] MCP server completo (stdio + SSE)
- [ ] KimiCode/OpenCode MCP transport
- [ ] Sandbox code execution tool
- [ ] Documentation + examples

---

## 5. Decisiones de Arquitectura Clave

1. **Gateway = Orchestrator, no Model Server**
   - NCM/Ollama/llama-cpp corren como servicios separados
   - Gateway solo enruta, valida, cachea, observa

2. **Thinkers como Post-processors**
   - `ThinkerLite` se aplica tras respuesta LLM (no reemplaza)
   - Math guard = bypass LLM para aritmética simple

3. **Free-tier First, Cloud Fallback**
   - `FREE_ONLY=1` por defecto
   - Circuit breaker + cooldowns evitan bucles

4. **MCP como Capa Unificada**
   - Tools locales + remotos bajo mismo protocolo
   - Clientes (KimiCode, OpenCode) hablan MCP, no APIs ad-hoc

5. **Quantization como Default**
   - Modelos locales siempre cuantizados (Q4_K_M / INT4)
   - Pipeline automatizado en `deploy/`

---

## 6. Métricas de Éxito (KPIs)

| KPI | Baseline | Target |
|---|---|---|
| Latencia p50 (math simple) | 1.14 s (NCM) / 3.35 s (Nemotron) | < 1 s local, < 2 s cloud |
| Throughput local (tok/s) | 380-680 (NCM batch) | > 1000 (INT4 batch) |
| Tool calling success rate | 100% (Ollama/llama-cpp) | 100% + parallel |
| Free-tier availability | Variable (cuotas) | > 99% via fallback |
| Math guard accuracy | 100% (deterministic) | 100% |
| Test coverage | 76 unit + smoke | > 200 (incl. property-based) |

---

## 7. Próximos Pasos Inmediatos

1. **Crear branch `improvements/2026-11-api-tools`**
2. **Implementar MCP server** (`app/mcp/`)
3. **Añadir quantization pipeline** (`deploy/quantize-models.sh`)
4. **Extender thinker-lite** con `CodeThinker` y `FactThinker`
5. **Actualizar `.env.example`** con nuevos parámetros
6. **Tests de integración MCP** con KimiCode real