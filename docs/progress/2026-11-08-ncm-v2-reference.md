# 2026-11-08: referencia NCM v2.0 y correcciones de evidencia

## Qué se hizo

- Se incorporó el informe final **NCM 2.0** aportado por el programador como
  `docs/references/ncm-primary-reference-v2.md`.
- La v1 (`ncm-primary-reference.md`) queda como **histórica/supersedida**, con
  banner y errata; no se borró.
- Se actualizaron el índice de referencias, el README raíz y los anexos
  (`ncm-advances`, `ncm-critical-review`, `ncm-benchmark-methodology`,
  `ncm-2610.14162`).

## Correcciones aplicadas

| Tema | v1 | v2 |
|---|---|---|
| KV-cache Llama-3-8B (B=64, S=512, t=576, BF16) | 19,3 GB | **9,13 GB** con GQA: 8 cabezas KV × 128 |
| KV-cache B=128 | 38,6 GB | **18,25 GB** |
| Prefill 8B, S=512 | 133 µs | **8,192 TFLOPs ≈ 8,3 ms** (cota inferior) |
| Punto de cruce \(B^*\) | 3,5 | **Abierto**; 3,5 no es un resultado demostrado |
| NCM vs AR | «nunca comparó AR» | El paper **sí** incluye AR en Sudoku (1,0% difícil), pero no benchmark de serving |
| TF32 H100 | 989 TFLOPS sin matiz | **494 densos / 989 con sparsity** |
| Sudoku 3,9%→56,6% | orden por incertidumbre | **orden aprendido** (PONDER); SRM por incertidumbre = 38,7% |

## Verificación

- **KV-cache:** \(64\cdot2\cdot32\cdot8\cdot128\cdot1088\cdot2 = 9.126.674.432\)
  bytes = 9,13 GB; B=128 = 18,25 GB.
- **Prefill:** \(2\cdot8\cdot10^9\cdot512 = 8,192\cdot10^{12}\) FLOPs;
  \(8,192/989 \approx 8,28\) ms.
- **`ncm-mlx` scratch:** `docs/EXPERIMENTS.md` E19-funded:
  98,10/83,40/40,30; E20: 97,25/79,60/33,25. También confirma
  «The original million-step E19 recipe remains unstarted».
- **PONDER:** arXiv:2610.23531, Tabla 1: orden aprendido 56,6% difícil;
  SRM greedy 38,7%; orden aleatorio 3,9%.
- **Servicio local:** `ncm-lm1b.service` activo en `127.0.0.1:11436`;
  `/health` reporta 724.800.640 parámetros, 3.410,4 MB de VRAM, carga 13,765 s,
  `unconditional=true`, `prompt_ignored=true`, `fixed_length=128`.
- **Gateway:** activo, con proveedor `ncm-lm1b` visible. No se inició, detuvo
  ni modificó ningún servicio para esta revisión.

## Límites

- No se ejecutó el benchmark H100 del informe ni la matriz de serving.
- No hay comparación pareada NCM vs AR: el NCM local es LM1B-large 725M
  unconditional y Qwen3.5-9B está inactivo, con otro tamaño/tokenizer/tarea.
- No hay checkpoints NCP-ArchPreview ni Cola2 instalados.
- No hay medición de energía ni trazas Nsight Compute.
- El benchmark reproducible propuesto sigue siendo trabajo pendiente.

## Referencias

- `docs/references/ncm-primary-reference-v2.md`
- https://arxiv.org/abs/2610.14162
- https://github.com/janmus1c/ncm-mlx/blob/main/docs/EXPERIMENTS.md
- https://arxiv.org/abs/2610.23531
- https://www.mindstudio.ai/blog/ncm-vs-llm-speed-benchmark-test
