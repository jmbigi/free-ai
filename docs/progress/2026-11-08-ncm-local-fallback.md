# 2026-11-08: fallback local NCM-Instruct-725M + capa thinker-lite

## Objetivo

Conectar un modelo local liviano como último fallback del gateway, después de
los proveedores remotos gratuitos, y mejorar su utilidad con una capa de
pensamiento/validación inspirada en `jmbigi/thinker` (GPL-3.0-only).

## Modelo y evidencia

- Checkpoint: `banan332/WB-catboy-NCM-Instruct-725M` (fine-tune instruct del
  NCM LM1B-large de HazyResearch).
- Parámetros: **724,800,640**.
- VRAM pico: **3,650 MB** en RTX 3070 Laptop 8 GB.
- Carga: **12.8 s**.
- Contexto: **128 tokens**.
- Licencia: **CC BY-NC-SA 4.0** (no comercial).
- Generación: best-of-3, `cfg=3.0`, `temperature=0.3`, `top_p=0.9`.
- Latencia: ~**3.0 s** por turno con 3 candidatos; matemática determinista
  ~0 s.

## Mejoras aplicadas (capa thinker-lite)

Archivo: `ncm_server.py` + `thinker_layer.py` en el directorio del checkpoint.

1. **Guardia aritmética determinista**: `7 times 8` → `7 * 8 = 56`, sin modelo.
2. **Best-of-3 + penalización** de filler, repetición y colapso de “cup”.
3. **Limpieza**: colapso de palabras vecinas duplicadas, espacios y puntuación.
4. **Clasificación de intención**: math, identity, recall, code, factual, chat.
5. **Validación antes de responder**: matemática, recall, diversidad factual.
6. **Reparación honesta**:
   - código → “128-token context is not enough for code.”;
   - factual repetitivo → “i'm not sure about that. this local model has weak
     factual knowledge.”;
   - factual limpio → prefijo “i'm not sure, but …”.
7. **Metadata** `gateway.thinker` con pasos, intención, confianza, validez y
   notas; el gateway la preserva.
8. **Compatibilidad**: `max_tokens`, `usage`, SSE con `[DONE]`, `/v1/models`,
   `/health`.

## Integración en el gateway

- Proveedor `ncm` (`app/providers/configured.py`), base local
  `http://127.0.0.1:11435/v1`, modelo `ncm/ncm-instruct-725m`.
- Variables: `NCM_LOCAL_ENABLED=1`, `NCM_LOCAL_BASE_URL`, `NCM_LOCAL_MODEL`.
- `FREE_ONLY`: el proveedor local se considera gratuito (sin costo upstream).
- **Último en `auto`**: `_build_auto_plan` pone NCM después de todos los
  remotos; nunca lo promociona por baja latencia.
- Servicio: `ncm-instruct.service` (systemd --user, loopback 11435,
  `Restart=always`).

## Evidencia de verificación

- `tests_router_unit.py`: 14/14, incluye NCM último y round-robin.
- `tests_smoke.py`: ALL PASS.
- Gateway → NCM (`cache:false`):
  - `7 times 8` → `7 * 8 = 56` (10 ms, `math_guard=true`).
  - capital de Francia → `i'm not sure about that...` (3.34 s).
  - `hello` → `i'm doing well, thank you for asking?` (2.99 s).
  - código → rechazo honesto por contexto 128.
- `GET /v1/models` incluye `ncm/ncm-instruct-725m`.
- `GET /v1/health` y `/health` OK; servicios `active/enabled`.

## Benchmark LM1B-large (2026-11-08)

Checkpoint oficial `lm1b/large` (725M), medido con `ncm_bench.py` en la RTX 3070,
`n=8`, `bs=8`, 128 tokens por muestra, `--no-cut`:

| Modelo | Params | VRAM pico | Carga | Throughput | Muestras/s |
|---|---:|---:|---:|---:|---:|
| LM1B-small | 97.1M | 1,373 MB | 9.1 s | **1,781 tok/s** | 13.9 |
| **LM1B-large** | **724.8M** | **3,838 MB** | 13.3 s | **522.9 tok/s** | 4.1 |
| NCM-Instruct-725M | 724.8M | 3,650 MB | 12.8 s | ~1.16 s/turno (best-of-3) | — |

Muestra real de LM1B-large:

> “events today will mark the first anniversary. the people including the
> coastguards said many drivers of the northumberland were being questioned…”

Sigue siendo texto tipo noticia LM1B, no chat; cualitativamente algo más
coherente que small, consistente con el escalado del paper (§4.5). Cabe completo
en 8 GB con ~4.2 GB de margen y sin offload.

**Veredicto para este equipo:** el mejor NCM oficial que cabe es **LM1B-large
725M** para generación unconditional; para chat experimental, el único NCM
instruct es **NCM-Instruct-725M** (128 tokens, hechos débiles). Small es más
rápido pero de menor calidad; medium no se descargó porque large ya cabe.

## Activación de LM1B-large (2026-11-08)

- Servicio `ncm-lm1b.service`: **active/enabled**, loopback `127.0.0.1:11436`.
- Modelo oficial `lm1b/large` (725M), **3,410 MB de VRAM** al cargar,
  `load_s=13.8`.
- Gateway → `ncm-lm1b/ncm-lm1b-large`: HTTP 200 en **0.823 s**; respuesta
  unconditional de 128 tokens; metadata `unconditional=true`,
  `prompt_ignored=true`, `fixed_length=128`, `buffered_stream=true`.
- **No se añadió a `auto`**: LM1B-large ignora el prompt y no es chat. Queda como
  modelo explícito para experimentación; `auto` no lo selecciona.
- Qwen/Ollama: desactivados por orden del programador; NCM-Instruct: inactivo.
- Metodología de benchmark aportada: `docs/references/ncm-benchmark-methodology.md`.

## Limitación real

NCM-Instruct-725M **no es un modelo de producción**: 128 tokens, inglés,
conocimiento factual débil, licencia no comercial y errores de coherencia.
La capa thinker reduce daño (no inventa matemática, no finge código, declara
incertidumbre), pero no crea capacidad que el modelo no tiene. Para calidad
general, un instruct de 7–9B (p. ej. Qwen3.5-9B) sigue siendo la opción
correcta; NCM queda como fallback experimental y explícito.
