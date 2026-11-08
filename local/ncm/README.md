# NCM LM1B-large local server

OpenAI-compatible local server for the official NCM **LM1B-large** checkpoint
(725M). It is an **unconditional** generator: it ignores prompts and always
produces a fixed 128-token news-style sample. It is exposed as an explicit
experimental model, **not** as an `auto` chat fallback.

## Requirements

- The HazyResearch NCM checkout and checkpoints outside this repo, by default
  `/home/kubuntu/ncm` (override with `NCM_HOME`).
- `artifacts/lm1b/large/generator.pt`, `artifacts/lm1b/tokenizer.pt` and the
  official `config/eval/lm1b-large.yaml`.
- A Python env with `torch` CUDA and the NCM requirements (by default
  `/home/kubuntu/ncm/.venv`).

## Run

```bash
NCM_HOME=/home/kubuntu/ncm \
  /home/kubuntu/ncm/.venv/bin/python -m uvicorn ncm_lm1b_server:app \
  --host 127.0.0.1 --port 11436
```

Health: `GET http://127.0.0.1:11436/health`
Models: `GET http://127.0.0.1:11436/v1/models`
Chat-compatible endpoint: `POST /v1/chat/completions` (prompt ignored).

Service example: `deploy/ncm-lm1b.service.example`.

## Benchmark local (reproducible)

`benchmark_ncm.py` mide el servicio activo: health check, warmup, batches
1/2/4 (el servidor limita `n` a 4), repeticiones, p50/p95, throughput y
validación de respuestas. No usa dependencias externas.

```bash
python3 local/ncm/benchmark_ncm.py \
  --batches 1,2,4 --repeats 5 --warmup 1 \
  --output docs/progress/2026-11-08-ncm-local-benchmark.json
```

Resultado medido el 2026-11-08 (RTX 3070 Laptop 8 GB, 5 repeticiones):

| Batch | p50 latencia | p95 latencia | p50 tok/s | Media tok/s |
|---:|---:|---:|---:|---:|
| 1 | 330,2 ms | 334,6 ms | 387,6 | 386,9 |
| 2 | 465,4 ms | 467,9 ms | 550,1 | 549,9 |
| 4 | 758,9 ms | 760,1 ms | 674,6 | 675,0 |

- Es una medición de **capacidad local**, no una comparación NCM vs AR.
- `n > 1` devuelve **todas** las choices y reporta `completion_tokens = 128*n`.
  La respuesta se construye en `response_builder.py` y está cubierta por tests.
- `ncm_bench.py` (medición interna, n=8/bs=8) dio 522,9 tok/s; no es comparable
  con este benchmark HTTP.
- JSON de evidencia: `docs/progress/2026-11-08-ncm-local-benchmark.json`.

## Honest limits

- Unconditional: it cannot answer or follow a chat prompt.
- Fixed output length: 128 tokens.
- No true streaming: the SSE is buffered until generation finishes.
- 725M parameters; ~3.4 GB VRAM; fits an 8 GB GPU.
- Use `NCM_LM1B_ENABLED=1` in the gateway to expose it as
  `ncm-lm1b/ncm-lm1b-large`; it is deliberately absent from `auto`.
