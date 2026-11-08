# 2026-11-08: benchmark local real de NCM LM1B-large

## Qué se hizo

Se añadió `local/ncm/benchmark_ncm.py`, un benchmark reproducible sin
dependencias externas para el servicio NCM LM1B-large activo en
`http://127.0.0.1:11436`. Mide health check, warmup, batches 1/2/4,
repeticiones, latencia p50/p95, throughput y valida las respuestas.

## Comando ejecutado

```bash
python3 local/ncm/benchmark_ncm.py \
  --batches 1,2,4 --repeats 5 --warmup 1 \
  --output docs/progress/2026-11-08-ncm-local-benchmark.json
```

## Resultados medidos

Servicio observado: `params=724.800.640`, `vram_mb=3410,4`, `load_s=13,765`,
`unconditional=true`, `prompt_ignored=true`, `fixed_length=128`.

| Batch | Tokens generados | p50 latencia | p95 latencia | p50 tok/s | Media tok/s |
|---:|---:|---:|---:|---:|---:|
| 1 | 128 | 341,0 ms | 343,8 ms | 375,4 | 379,1 |
| 2 | 256 | 463,5 ms | 466,6 ms | 552,3 | 551,6 |
| 4 | 512 | 757,4 ms | 759,3 ms | 676,0 | 676,4 |

Las cinco repeticiones de cada batch están en el JSON de evidencia:
`docs/progress/2026-11-08-ncm-local-benchmark.json`.

## Prueba end-to-end por el gateway

También se probó la ruta real del gateway:

```text
POST http://127.0.0.1:8000/v1/chat/completions
model=ncm-lm1b/ncm-lm1b-large
```

Resultado: **HTTP 200**, `model=ncm-lm1b-large`, 461 caracteres, `latency_ms=339`,
`gateway.local=true`, `unconditional=true`, `prompt_ignored=true`,
`fallback_used=false`, `selected=ncm-lm1b/ncm-lm1b-large`,
`selected_is_free_tier=true`. La petición usó la API key del gateway desde
`.env`; la clave no se imprimió ni se commiteó.

## Hallazgo funcional

Para `n > 1`, el servidor genera `n` muestras pero devuelve solo la primera
`choice` y reporta `completion_tokens=128`. El benchmark cuenta `128*n` y
registra el desajuste (`usage_matches_batch=false`). El gateway usa `n=1`, así
que la ruta de chat normal no está afectada. Corregir la respuesta para `n>1`
requiere modificar y reiniciar `ncm-lm1b`; no se reinició ningún servicio.

## Pruebas

```bash
.venv/bin/python -m unittest tests_ncm_benchmark_unit.py -v
```

Resultado: **11 tests OK**. Los tests cubren percentiles, resumen, parseo de
batches y validación de respuestas, sin red.

También se verificó:

- `tests_router_unit.py`: **17 tests OK, 3 skipped**.
- `python3 -m py_compile local/ncm/benchmark_ncm.py tests_ncm_benchmark_unit.py`: OK.
- Servicio caído simulado en `127.0.0.1:9`: el benchmark falla con error claro
  y exit 1; no inventa resultados.
- Batch inválido `9`: argparse lo rechaza con exit 2.

## Límites

- Medición de capacidad local en una RTX 3070 Laptop 8 GB; no es H100.
- No es una comparación NCM vs AR: el NCM es unconditional y Qwen está inactivo.
- No se midieron NCP, Cola2, energía, Nsight Compute ni serving concurrente.
- El servidor serializa generación con un lock; los batches no son concurrencia
  real de múltiples requests.
- El benchmark es secuencial y de baja concurrencia; no sustituye al benchmark
  completo propuesto en la referencia NCM v2.

## Estado de servicios

- `ncm-lm1b`: activo durante la medición.
- `free-ai-gateway`: activo.
- `thinker`: activo.
- `ollama` y `ncm-instruct`: inactivos.
- No se inició, detuvo ni reinició ningún servicio para esta prueba.
