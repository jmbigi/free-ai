# NCM: evidencia verificada y límites (2026-11-08)

> Referencia principal consolidada: [ncm-primary-reference-v2.md](ncm-primary-reference-v2.md).
> La v1 ([ncm-primary-reference.md](ncm-primary-reference.md)) queda como
> histórica. Este documento es un anexo de verificación y límites.

Regla asociada: `AGENTS.md` → regla 14 (NCM como tercera vía, evidencia dual).

## Paper primario

**Kumbong et al., “Next-Concept Modeling: Fast, Parallel Coarse-to-Fine Text
Generation”, arXiv:2610.14162v1 (09 Oct 2026).**
https://arxiv.org/abs/2610.14162

- Arquitectura: VQ-VAE multiescala + transformer que genera niveles coarse-to-fine.
- Eficiencia declarada en el abstract: **21×** más rápido que el mejor DLM en
  LM1B, **10×** en OpenWebText, **31×** en XSum.
- Tokens de entrenamiento: **~4.9× menos** en LM1B y **~4× menos** en OWT
  (§4.6, Figura 7).
- Sudoku (Tabla 3): NCM **86.1%** en difícil; FMLM+ **81.3%**; AR greedy **1.0%**.
- Escalado: generadores de **97M, 317M y 725M** en LM1B; los experimentos
  principales son ~100M (§4.5, Apéndice I).
- Límites declarados por los autores (Apéndice I): tokenizer y generador
  separados por tarea, jerarquía y longitudes fijas, dependencia de un
  tokenizer VQ-VAE entrenado aparte, artefactos en transiciones de nivel.

## Benchmark independiente (secundario)

**MindStudio, “NCM vs LLMs: Independent Speed Benchmark Results Explained”,
29 Oct 2026.** https://www.mindstudio.ai/blog/ncm-vs-llm-speed-benchmark-test

- Petición única: NCM ~**4×** más rápido que un AR comparable en traducción y
  ~**2×** en resumen largo.
- **Batch de 64**: el AR comparable gana; NCM procesa ~4× más posiciones
  totales por respuesta y el cuello de botella pasa de memoria a cómputo.
- Sudoku: reproduce el 86%, pero un DLM del mismo tamaño con decodificación por
  confianza se acerca; la ventaja no es solo la arquitectura.
- Límites observados: salida de tamaño fijo, sin streaming real, sin código de
  entrenamiento público, no probado por encima de ~1B, prompt caching con fallos.

## Líneas relacionadas

### ConceptLM / NCP

**Liu et al., “Next Concept Prediction in Discrete Latent Space Leads to
Stronger Language Models”, arXiv:2602.08984 (09 Feb 2026).**
https://arxiv.org/abs/2602.08984

- NCP predice conceptos discretos (varios tokens) además de NTP.
- ConceptLM se entrena desde cero de **70M a 1.5B** parámetros, hasta **300B**
  tokens; gana consistentemente en **13 benchmarks**.
- Continual pretraining en un Llama de **8B** también mejora con NCP.

### NCP-ArchPreview

**Intern-NCP Team, “NCP-ArchPreview Technical Report”, arXiv:2609.10715
(09 Sep 2026).** https://arxiv.org/abs/2609.10715

- **8.9B** parámetros, **5.73T** tokens de Dolma-3.
- Con **51.3%** de los tokens alcanza la loss final de OLMo-3-7B.
- Tras el pretraining completo: **+2.45** en macro-average downstream y
  **+5.99** en GSM8K frente a OLMo-3-7B.
- El espacio latente sigue siendo útil: actualizar solo el módulo VQ (17M)
  sirve como interfaz de adaptación de dominio.

### Cola2

**ByteDance-Seed, “Cola2”, arXiv:2610.31305 / Hugging Face.**
https://huggingface.co/ByteDance-Seed/Cola2

- Modelo latente continuo: VAE de compresión dinámica + DiT + decoder de spans.
- **346.03B** tokens; **60.10** de promedio en 8 tareas.
- Supera a Llama-3-8B **solo** en HellaSwag (41.75 vs 39.21) y StoryCloze
  (80.42 vs 79.49); pierde en el promedio global (60.10 vs 66.25).
- Es un modelo base, no un instruct/chat; el checkpoint liberado es grande
  (~9B) para 8 GB de VRAM.

## Referencia aportada por el programador

- `docs/references/ncm-critical-review.md`: revisión crítica con formalismo,
  tabla comparativa y preguntas abiertas. Incluye una sección de verificación
  que confirma la paridad fp64/fp32 de `ncm-mlx` y las tasas Sudoku, y aclara
  que 8.9B corresponde a NCP-ArchPreview, no a ConceptLM.

## Metodología de benchmark aportada por el programador

- `docs/references/ncm-benchmark-methodology.md`: propuesta NCM vs AR/vLLM
  (FLOPs, TTFT/TFO, throughput concurrente). Incluye correcciones: el
  pseudocódigo de `fetchall_nodes()` no es API válida de PyTorch Profiler; el
  “TTFT-NCM coarse” no es un token usable; la matriz H100 no aplica a 8 GB; y
  la expectativa “batch ≥32” se midió en batch 64.

## Análisis Roofline aportado por el programador

- `docs/references/ncm-roofline-analysis.md`: comparación AR vs NCM bajo
  Roofline. Corrección clave: en H100 SXM5 FP16/BF16 dense el ridge point es
  **~295 FLOP/byte** (989 TFLOPS / 3.35 TB/s), no 15–50. NCM no es
  “enmascaramiento continuo”; es coarse-to-fine con códigos discretos y niveles
  secuenciales. La intensidad 10–30 FLOP/byte y los porcentajes de utilización
  son estimaciones, no mediciones.

## Correcciones de la referencia v2 (2026-11-08)

- **KV-cache GQA:** Llama-3-8B tiene 8 cabezas KV de 128 dimensiones
  (\(d_{\text{KV}}=1024\)), no \(d=4096\). Para \(S=512\), \(t=576\), BF16:
  **9,13 GB** a B=64 y **18,25 GB** a B=128. Las cifras v1 de 19,3/38,6 GB
  quedan sustituidas.
- **Prefill:** para 8B y \(S=512\), \(2PS=8.192\) TFLOPs; a 989 TFLOPS la cota
  inferior es **≈8,3 ms**, no 133 µs. Es aritmética, no una latencia medida.
- **TF32:** H100 SXM tiene **494 TFLOPS densos** (989 con sparsity). BF16 denso
  989, sparse 1.979.
- **Sudoku 3,9%→56,6%:** pertenece a **orden aprendido** (PONDER,
  arXiv:2610.23531); el orden greedy por incertidumbre reporta 38,7%. No
  atribuir el 56,6% a un orden basado en incertidumbre.
- **NCM vs AR:** el paper sí incluye un baseline AR en Sudoku (1,0% difícil),
  pero no una comparación sistemática de serving. El punto de cruce \(B^*\)
  sigue abierto; \(B^*\approx3,5\) no es un resultado demostrado.
- **`ncm-mlx` scratch:** 98,10/83,40/40,30 (seed 0) y 97,25/79,60/33,25
  (seed 1) son modelos más pequeños y recetas distintas, no una replicación
  limpia del entrenamiento oficial.
- **Benchmark completo:** la comparación NCM vs AR vs NCP vs Cola2 con FLOPs,
  HBM, latencia, throughput y energía **no se ejecutó**; sigue pendiente.

## Implicaciones para este repositorio

- No afirmar “NCM es siempre más rápido”: la ventaja depende de single-request
  vs batch y del tipo de tarea.
- NCM no hace streaming real: la respuesta no es legible hasta el último nivel.
  Cualquier SSE de NCM es **buffered**, no token-by-token.
- NCM-Instruct-725M es un fine-tune comunitario, no el modelo del paper; su
  contexto de 128 tokens y su calidad factual son limitadas.
- El mejor NCM “para este equipo” depende de la tarea: LM1B-large (725M) para
  generación unconditional; XSum/WMT14/Sudoku para sus tareas; Instruct-725M
  para chat experimental. Medir VRAM y throughput antes de activar.
- No decidir activación/desactivación de servicios por cuenta propia (regla 15).
