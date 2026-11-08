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

Servicio observado: `params=724.800.640`, `vram_mb=3410,4`, `load_s=12,671`,
`unconditional=true`, `prompt_ignored=true`, `fixed_length=128`.

| Batch | Tokens generados | p50 latencia | p95 latencia | p50 tok/s | Media tok/s |
|---:|---:|---:|---:|---:|---:|
| 1 | 128 | 330,2 ms | 334,6 ms | 387,6 | 386,9 |
| 2 | 256 | 465,4 ms | 467,9 ms | 550,1 | 549,9 |
| 4 | 512 | 758,9 ms | 760,1 ms | 674,6 | 675,0 |

Las cinco repeticiones de cada batch están en el JSON de evidencia:
`docs/progress/2026-11-08-ncm-local-benchmark.json`.

## Prueba end-to-end por el gateway

También se probó la ruta real del gateway:

```text
POST http://127.0.0.1:8000/v1/chat/completions
model=ncm-lm1b/ncm-lm1b-large
```

Resultado: **HTTP 200**, `model=ncm-lm1b-large`, 461 caracteres, `latency_ms=329`,
`gateway.local=true`, `unconditional=true`, `prompt_ignored=true`,
`fallback_used=false`, `selected=ncm-lm1b/ncm-lm1b-large`,
`selected_is_free_tier=true`, `gateway.batch=1`. La petición usó la API key del
gateway desde `.env`; la clave no se imprimió ni se commiteó.

## Corrección aplicada: `n > 1`

Antes, el servidor generaba `n` muestras pero devolvía solo la primera `choice`
y reportaba `completion_tokens=128`. Se corrigió con
`local/ncm/response_builder.py`:

- Devuelve **todas** las choices, con índices 0..n-1.
- `usage.completion_tokens = 128*n`.
- `gateway.batch` y `gateway.samples` reflejan el batch.
- El streaming emite un chunk por choice y un chunk final con `stop` para cada
  índice.

Verificación real después de reiniciar `ncm-lm1b`:

| Prueba | Resultado |
|---|---|
| `n=4` no-stream | 4 choices, índices 0..3, `completion_tokens=512` |
| `n=2` stream | 3 chunks, índices 0/1, `completion_tokens=256` |
| `n=1` vía gateway | HTTP 200, 461 caracteres, `gateway.batch=1` |
| Benchmark `n=1/2/4` | `choices=1/2/4`, `usage_match=true` en todos |

Se guardó backup del archivo de runtime anterior en
`/home/kubuntu/ncm/ncm_lm1b_server.py.bak-20261108-195849`. El servicio
`ncm-lm1b` se reinició para cargar el fix y volvió a `active` en ~12 s.

## Pruebas

```bash
.venv/bin/python -m unittest tests_ncm_benchmark_unit.py -v
```

Resultado: **12 tests OK**. Los tests cubren percentiles, resumen, parseo de
batches y validación de respuestas, sin red.

```bash
.venv/bin/python -m unittest tests_ncm_response_unit.py -v
```

Resultado: **6 tests OK**. Cubren `n=1`, `n=4`, usage `128*n`, choices,
streaming y validación de textos vacíos.

También se verificó:

- `tests_router_unit.py`: **17 tests OK, 3 skipped**.
- `python3 -m py_compile local/ncm/benchmark_ncm.py local/ncm/response_builder.py tests_ncm_benchmark_unit.py tests_ncm_response_unit.py`: OK.
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
- `ncm-lm1b` se reinició **una vez** para aplicar el fix de `n>1`; volvió a
  `active` y el health check quedó `ok/loaded=true`. No se tocaron los demás
  servicios.
