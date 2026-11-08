# Next-Concept Modeling (NCM): Fundamentos, Ecosistema de Investigación y Evaluación Crítica de su Rendimiento Operacional

**Documento técnico consolidado — Noviembre 2026**

> **Referencia principal del proyecto.** Documento aportado por el programador.
> Se conserva el texto consolidado y se añade una **Nota editorial de
> verificación** al final con el estado de las fuentes, correcciones y
> limitaciones. No usar una cifra sin comprobar su nota (regla 14).

---

## Resumen ejecutivo

Next-Concept Modeling (NCM) es un marco de generación de texto presentado por el laboratorio Hazy Research de Stanford y Together AI que sustituye la predicción token a token por una generación jerárquica coarse-to-fine: un tokenizador VQ-VAE multiescala comprime el texto en K niveles de códigos discretos, y un transformer predice todos los códigos de un nivel en paralelo antes de pasar al siguiente. El resultado reportado es una generación 10–31× más rápida que los modelos de difusión de lenguaje con calidad comparable o superior, usando 4–5× menos tokens de entrenamiento.

Este documento consolida la evidencia disponible, la replicación independiente, las tres rutas divergentes que el concepto de "predicción más allá del token" ha generado (NCM, ConceptLM/NCP y Cola2), y una evaluación crítica de los protocolos de benchmark propuestos para comparar NCM contra transformers autorregresivos (AR) servidos con vLLM. La conclusión central es que **NCM acierta en la dirección cualitativa —gana en latencia de solicitud única, pierde en throughput concurrente— pero los protocolos cuantitativos que se han propuesto para formalizar esa frontera contienen errores que invalidan sus predicciones numéricas**. Se documentan las correcciones necesarias para que un benchmark de Capa A (paradigma) sea defendible.

---

## 1. El paradigma NCM: arquitectura y mecánica

### 1.1 Dos etapas, K pasos secuenciales

NCM opera en dos fases:

**Etapa 1 — Tokenizador multiescala residual VQ-VAE.** Un encoder asigna al texto de longitud L una jerarquía de códigos discretos \(r_1, \dots, r_K\), donde \(\ell_1 < \ell_2 < \dots < \ell_K = L\) y cada nivel cuantiza el residuo que deja el nivel anterior. El paper reporta una precisión de reconstrucción exacta de **99,99% en OpenWebText, 99,86% en LM1B y 100% en Sudoku** (donde un solo dígito erróneo invalidaría la solución).

**Etapa 2 — Generador coarse-to-fine.** Con el tokenizador congelado, un transformer predice el nivel \(k\) condicionado en la reconstrucción acumulada de los niveles \(1 \dots k-1\), generando **todos los \(\ell_k\) códigos de ese nivel en un solo forward pass**. Tras el nivel \(K\), el decodificador VQ-VAE mapea la reconstrucción acumulada a distribuciones de token en las L posiciones.

La generación requiere **K pasos secuenciales**, no L. Para XSum (\(K=8\)) o WMT14 (\(K=11\)), esto significa 8 u 11 pasos frente a los 48–64 pasos de decodificación de un modelo AR de tamaño comparable.

### 1.2 Atención block-diagonal

A diferencia de un transformer estándar, NCM usa **atención block-diagonal** en el generador: cada bloque objetivo atiende solo a sí mismo y al prefijo (en generación condicional), no a los bloques anteriores. El paper reporta que esta elección supera a la atención block-causal (Gen. PPL 15,41 vs. 19,63 en TinyStories) y reduce el tiempo de muestreo en un 21–40%.

### 1.3 Resultados reportados

| Tarea | Métrica | NCM | Mejor baseline | Ventaja reportada |
|---|---|---|---|---|
| LM1B (no condicional) | Gen. PPL / Tiempo | Mejor que DUO | DUO | **21× más rápido** |
| XSum (resumen) | ROUGE-L / Tiempo | 28,0 | AURORA-LM 26,6 | **31× más rápido** |
| Sudoku (difícil) | % tableros resueltos | **86,1%** | FMLM+ 81,3% | 12 NFE vs. 16–128 |
| Entrenamiento (LM1B) | Tokens | **13,36B** | ~66B (DLMs) | **4,9× menos** |

Los resultados de Sudoku son particularmente citados: un modelo de **25M de parámetros** resuelve el 86,1% de los tableros difíciles en **12 pasos**, frente al 1,0% de un AR comparable y el 81,3% de FMLM+ con 16 pasos.

---

## 2. Replicación independiente: `ncm-mlx` y la verificación numérica

La existencia de una implementación independiente es un indicador de calidad poco común en la literatura de generación de texto. **`ncm-mlx`** es un port de NCM al framework MLX de Apple, publicado en PyPI, que permite ejecutar los checkpoints oficiales en GPUs de Apple Silicon sin PyTorch.

### 2.1 Consistencia numérica

El port reporta coincidencia de logits con los checkpoints oficiales de PyTorch en precisión fp64 con discrepancias máximas de **3,2×10⁻¹⁰ (TinyStories) y 1,2×10⁻¹³ (Sudoku)**. La generación greedy produce resultados idénticos al modelo oficial. Esto valida que la arquitectura y el flujo de inferencia fueron replicados correctamente.

### 2.2 Reproducción robusta en Sudoku, pero sensible al entrenamiento desde cero

En el conjunto de test completo, la implementación independiente alcanza **99,40% / 96,30% / 86,20%** (fácil / medio / difícil), prácticamente idénticos al paper. Sin embargo, al entrenar un generador **más pequeño y desde cero** con dos semillas distintas, las tasas en dificultad difícil caen a **40,30% y 33,25%**, muy por debajo del 86,1% oficial. Esto sugiere que el resultado de Sudoku **depende de la receta exacta de entrenamiento** y no debe interpretarse como una propiedad robusta del paradigma.

### 2.3 Un experimento controlado a escala de juguete

El modelo `ncm-mlx-tinyworld` (5,0M de parámetros de generador + 1,3M de codec, entrenado sobre un lenguaje sintético de 32 caracteres) permite una comparación limpia contra un AR del mismo tamaño (4,8M) en Apple M5 Pro. Los resultados son reveladores:

| Métrica | NCM (5,0M) | AR (4,8M) |
|---|---|---|
| Frases válidas (T=1,0) | 89,8% | **98,6%** |
| Válidas y no vistas | 16,3% | **23,5%** |
| Llamadas al modelo | **6 + 1 decode** | 32 |
| Latencia p50, batch 1 | **4,5 ms** | 19,8–30,5 ms |
| Latencia p50, batch 256 | **37,8 ms** | 49,8 ms |

A esta escala mínima, **NCM es más rápido pero menos preciso**: el AR iguala o supera la validez del NCM, y la brecha de calidad no se cierra hasta que el modelo crece. La ventaja de latencia, en cambio, aparece desde el batch 1 y persiste hasta batch 256 en esta tarea corta (32 caracteres), donde el costo del codec no domina.

---

## 3. El ecosistema post-NCM: tres rutas divergentes

La intuición central de NCM —predecir en una granularidad más gruesa que el token— ha generado tres líneas de investigación con diseños arquitectónicos y objetivos fundamentalmente distintos.

### 3.1 Ruta NCM: generación jerárquica discreta (Stanford / Together AI)

**Qué cambia:** la unidad de generación (códigos discretos en jerarquía) y el orden de inferencia (K pasos por niveles, paralelismo dentro de cada nivel).
**Qué optimiza:** **velocidad de inferencia**. Menos pasos secuenciales, menor costo por paso en niveles gruesos.
**Limitación estructural:** jerarquía K y longitudes \(\ell_k\) fijas; un input de 10 tokens atraviesa los mismos K niveles que uno de 1.024. El paper reconoce esto explícitamente.
**Escala validada:** 725M parámetros (LM1B).

### 3.2 Ruta ConceptLM / NCP-ArchPreview: predicción de conceptos como objetivo auxiliar (Shanghai AI Lab)

**Qué cambia:** **nada en la interfaz de inferencia**. El backbone sigue siendo autorregresivo estándar (NTP). Se añade un objetivo auxiliar de **predicción del siguiente concepto (NCP)** durante el entrenamiento, usando un espacio latente discreto construido con VQ.
**Qué optimiza:** **eficiencia de entrenamiento**. El objetivo NCP actúa como una señal de supervisión más rica que fuerza representaciones internas de más largo alcance.
**Evidencia clave:** **NCP-ArchPreview** (8,9B parámetros, 5,73T tokens de Dolma-3) alcanza el mismo loss de preentrenamiento que **OLMo-3-7B consumiendo solo el 51,3% de los tokens**, con una mejora de **+5,99 puntos en GSM8K**.
**Diferencia crucial con NCM:** son propuestas **ortogonales**. NCM cambia *qué* se genera; NCP cambia *cómo se entrena*. Podrían combinarse.

### 3.3 Ruta Cola2: generación jerárquica en espacio latente continuo (ByteDance)

**Qué cambia:** comparte con NCM la generación coarse-to-fine, pero opera en un **espacio latente continuo** en lugar de códigos discretos. Un VAE con compresión dinámica agrupa el texto en "spans" semánticos de longitud variable; un Diffusion Transformer (DiT) genera los vectores latentes en orden jerárquico; un decodificador reconstruye el texto.
**Qué optimiza:** **eficiencia de datos**. La compresión continua permite representaciones más compactas que los códigos discretos.
**Evidencia clave:** un checkpoint con **346B tokens** supera a Llama-3-8B (15T+ tokens) en HellaSwag y StoryCloze.
**Diferencia con NCM:** misma filosofía de generación, representación opuesta (continua vs. discreta). La comparación directa entre ambas rutas no se ha publicado.

### 3.4 Tabla comparativa

| Dimensión | **NCM** | **ConceptLM / NCP** | **Cola2** |
|---|---|---|---|
| **Unidad de generación** | Códigos discretos jerárquicos | Tokens + conceptos (auxiliar) | Vectores latentes continuos |
| **Orden de inferencia** | **K pasos por niveles** (paralelo intra-nivel) | **Token a token** (AR estándar) | **Bloques paralelos** en latente |
| **Fuente de eficiencia** | **Velocidad de inferencia** | **Eficiencia de entrenamiento** | **Eficiencia de datos** |
| **Cambia la inferencia** | Sí | No | Sí |
| **Escala validada** | 725M | **8,9B** | ~346B tokens |
| **Ventaja demostrada** | 10–31× speedup vs. DLMs; Sudoku | ~2× convergencia; +6 pts GSM8K | Supera a Llama-3-8B con 40× menos datos |

---

## 4. La tensión operacional: Roofline, KV-cache y el punto de cruce \(B^*\)

### 4.1 El límite físico de AR en decode

En decodificación autorregresiva, cada paso debe leer los pesos del modelo desde HBM. Para un modelo de \(P\) parámetros en BF16 (\(2\) bytes por parámetro) sobre H100 SXM (3,35 TB/s), el tiempo mínimo por paso es:

\[
T_{\min}^{\text{step}} = \frac{2P}{\text{BW}} = \frac{2 \times 8 \times 10^9}{3.35 \times 10^{12}} \approx 4.78 \text{ ms}
\]

Para \(L=128\), el mínimo absoluto es **611 ms**. Cualquier benchmark que reporte menos de este valor para un modelo de 8B en BF16 es físicamente imposible.

### 4.2 El KV-cache mantiene a AR en régimen memory-bound

La suposición frecuente de que AR "se vuelve compute-bound" a batch grande es incorrecta para contextos largos. El tráfico de KV-cache **no se amortiza entre muestras**:

\[
M_{\text{KV}}(B, t) = B \cdot 2 N_{\text{layers}} d (S+t) \cdot \text{bpk}
\]

Para Llama-3-8B (\(N=32\), \(d=4096\)), \(S=512\), \(t=576\), \(B=64\): \(M_{\text{KV}} \approx 19.3\) GB, comparable a los 16 GB de pesos. A \(B=128\), \(M_{\text{KV}} \approx 38.6\) GB. **AR sigue siendo memory-bound en todo el rango \(B \in [1, 128]\)** para \(S=512\).

### 4.3 NCM es compute-bound, pero su desventaja es de cómputo total

NCM evita el cuello de botella de memoria de AR porque procesa \(\ell_k\) posiciones en paralelo en cada nivel. Pero \(\sum \ell_k \approx 2L\) a \(4L\) (dependiendo del schedule), y \(\sum \ell_k^2 > L^2/2\). Para un schedule geométrico de razón 2, \(\sum \ell_k \approx 2L\) y \(\sum \ell_k^2 \approx \frac{4}{3}L^2 > \frac{1}{2}L^2\). **NCM hace más FLOPs totales que AR**, y su ventaja desaparece cuando el hardware está saturado de cómputo.

### 4.4 El punto de cruce \(B^*\): la evidencia empírica

Pruebas independientes en un DGX Spark confirman la inversión: **NCM es ~4× más rápido en solicitud única** (traducción) y ~2× en resumen, pero **un AR estándar lo supera a partir de batch 64**, porque NCM hace más cómputo total por respuesta aunque necesite menos pasos. El paper original **nunca comparó contra un AR estándar**, solo contra modelos de difusión.

---

## 5. Evaluación crítica de los protocolos de benchmark de Capa A

Se han propuesto varios protocolos para formalizar la frontera operacional AR vs. NCM. A continuación se sintetizan sus errores y correcciones.

### 5.1 Errores en el modelo analítico de FLOPs y Roofline

**Error 1 — La implicación \( \sum \ell_k \gg L \Rightarrow F_{\text{NCM}} > F_{\text{AR}} \) es inválida.** La suma \(\sum \ell_k\) controla solo el término lineal en \(P\); el término cuadrático depende de \(\sum \ell_k^2\). La conclusión es cierta en la práctica, pero por el término cuadrático, no por la premisa escrita.

**Error 2 — El modelo de AR omite el KV-cache.** Modelar \(M = P \cdot \text{bpp}\) subestima el tráfico de memoria en un factor \(1 + B \cdot 2Nd(S+t)\text{bpk}/(P\text{bpp})\), que para LM1B a \(B=64\) es ~1,78× y para XSum a \(B=8\) es ~1,94×. Esto **subestima \(B^*\)** en un factor de 2–3×.

**Error 3 — NCM no es "directamente compute-bound".** A \(B\) pequeño y \(\ell_k\) pequeño, los niveles tempranos son **memory-bound**. Para LM1B, el nivel 1 (\(\ell_1=1\)) solo se vuelve compute-bound a \(B \approx 300\). La simplificación \(T_{\text{NCM}} \approx B \cdot F_{\text{gen}}/\text{TFLOPS}\) sobreestima el throughput a \(B=1\) en ~4,5×.

**Error 4 — \(F_{\text{gen}}^{\text{NCM}}\) sobreestima el costo si el prefijo se cachea.** El protocolo usa \(\sum_k (S+\ell_k)^2\), que cuenta \(K\) veces el costo de autoatención del prefijo \(S^2\). Si el prefijo se cachea entre niveles, el protocolo sobreestima \(F_{\text{gen}}\) en \((K-1)S^2 \cdot 4Nd\). Para XSum, esto es ~541 GFLOPs, un 48% del \(F_{\text{gen}}\) total.

**Error 5 — Peak TFLOPS vs. TFLOPS efectivos.** Para modelos de ~100M, el TFLOPS efectivo es 20–40% del peak. Usar peak **sobreestima \(B^*\)** en un factor de 2,5–5×.

**Error 6 — Prefill despreciado.** Para \(S=512\), \(T_{\text{prefill}} \approx 133\,\mu s\), comparable a \(T_{\text{decode}}\) por muestra. Descartarlo **subestima \(B^*\)**.

### 5.2 Cancelación de errores y el peligro de la falsa plausibilidad

Los errores tienen **signos opuestos y magnitudes comparables**: la omisión del KV-cache subestima \(B^*\); el uso de peak TFLOPS y la sobreestimación de \(F_{\text{gen}}\) lo sobreestiman. El resultado final puede **parecer razonable por cancelación accidental**, no por corrección. Esto es metodológicamente peligroso: el protocolo no identifica cuál régimen está midiendo y, por tanto, no se puede saber cuándo el resultado es fiable.

### 5.3 Errores en el script de perfilado `profile_h100_roofline.py`

El script propuesto para medir \(\mu\) y la saturación de HBM contiene errores que invalidan la medición:

- **`self_cuda_memory_usage` no es tráfico a HBM.** Mide el cambio neto de memoria asignada en el pool de CUDA, no los bytes leídos/escritos. Para pesos pre-asignados, el resultado es ≈0, produciendo `mem_saturation ≈ 0%` incluso para un GEMV que satura el ancho de banda.
- **`with_flops=True` subestima los FLOPs.** Solo cuenta operadores con fórmula registrada; kernels fusionados, FlashAttention o custom ops reportan `flops=None` o `0` y se omiten silenciosamente.
- **`key_averages()` puede doble-contar tiempo.** Suma `cuda_time_total` sobre padres e hijos de la jerarquía de dispatch (`aten::linear → aten::addmm → cutlass::gemm`), inflando el tiempo en 2–3×.
- **Una capa lineal no representa un paradigma.** El script mide un GEMV (AR) contra un GEMM (NCM), demostrando un hecho de libro de texto, no una propiedad de los paradigmas.
- **"μ > 0.3 ⇒ compute-bound" es falso.** Para el GEMM de (1, 128, 4096)×(4096, 11008), la intensidad aritmética es ~122 FLOPs/Byte, por debajo del ridge point de H100 (~295 FLOPs/Byte). **Sigue siendo memory-bound**, solo más cerca del ridge point. μ alto y compute-bound son cosas distintas.

### 5.4 Errores en la tabla de emulación numérica

La tabla que reporta latencias y throughputs para \(B \in [1, 128]\) contiene:

- **AR a \(B=1\) = 462,5 ms es físicamente imposible** (mínimo ≥611 ms).
- **Etiquetas de régimen erróneas:** AR está marcado como "Compute-Bound" a \(B=32, 64, 128\), cuando el KV-cache lo mantiene memory-bound en todo el rango.
- **Inconsistencia de escalado:** NCM pasa de 154,2 ms a \(B=1\) a 920,4 ms a \(B=64\), un ratio de 6× para 64× más trabajo. Para un workload compute-bound, el tiempo debería crecer linealmente con \(B\) una vez saturado.
- **\(B^* \approx 64\) no se sigue del modelo declarado.** Con los parámetros dados (Llama-3-8B, \(S=512\), \(L=128\), H100, \(\mu=0,4\)), el cálculo correcto da **\(B^* \approx 3,5\)**: NCM gana solo para \(B \le 3\) y AR desde \(B \approx 4\).

---

## 6. Limitaciones reconocidas y direcciones futuras

El paper de NCM reconoce explícitamente:

1. **Jerarquía fija:** \(K\) y \(\ell_k\) no se adaptan a la complejidad de la entrada. Un esquema dependiente del input mejoraría la eficiencia.
2. **Tokenizador desacoplado:** El VQ-VAE se entrena por separado y se congela. Un entrenamiento end-to-end alinearía representación y objetivo generativo.
3. **Escala limitada:** Los experimentos principales usan ~100M de parámetros; el escalado llega a **725M** en LM1B. No hay validación a escala de miles de millones.
4. **Artefactos en transiciones de nivel:** Generaciones fluidas en general, pero incoherencias ocasionales en los límites coarse-fine.
5. **Sin streaming:** La respuesta completa no es legible hasta el último paso de refinamiento. Esto es una limitación funcional, no solo de latencia.
6. **Errores de reconstrucción:** Incluso con 99,99% de precisión, el tokenizador ocasionalmente intercambia entidades nombradas ("Sydney" → "Melbourne") o altera numerales ("1956" → "1957").

---

## 7. Conclusiones

**NCM demuestra que la generación coarse-to-fine con códigos discretos es una alternativa viable y de alta calidad** a la difusión y a la autoregresión, al menos en el régimen de ~100M de parámetros y en tareas con estructura global. La replicación independiente (`ncm-mlx`) confirma la corrección técnica del paradigma, pero revela su sensibilidad a la receta de entrenamiento.

**El ecosistema post-NCM se ha diversificado en tres rutas ortogonales:** NCM optimiza velocidad de inferencia; ConceptLM/NCP optimiza eficiencia de entrenamiento (validado a 8,9B); Cola2 optimiza eficiencia de datos mediante latentes continuos. La combinación de estas rutas —generación jerárquica + objetivo de conceptos auxiliar— es una dirección abierta.

**La ventaja operacional de NCM es real pero contingente.** Gana en latencia de solicitud única (~4× frente a AR emparejado) y pierde en throughput concurrente a partir de batch ~64. El punto de cruce depende del hardware, la longitud de contexto y el schedule de niveles. Los protocolos que intentan formalizar \(B^*\) analíticamente deben corregir la omisión del KV-cache, el tratamiento del régimen memory-bound de NCM en niveles tempranos, el uso de TFLOPS efectivos en lugar de peak, y la inclusión explícita del decodificador VQ.

**Nada en las hojas de ruta actuales de producción necesita cambiar todavía.** Los sistemas en producción siguen ejecutándose sobre modelos autorregresivos, y NCM no ha sido validado más allá de 725M de parámetros ni comparado de forma sistemática contra AR estándar en el paper original. Es una línea de investigación prometedora, no una tecnología lista para despliegue.

---

## Referencias

1. Kumbong, H., Khare, I. S., Mlauzi, I., Woen, A., Ding, C., Buchanan, E. K., Arora, S., Mirhoseini, A., & Ré, C. (2026). *Next-Concept Modeling: Fast, Parallel Coarse-to-Fine Text Generation*. arXiv:2610.14162. https://arxiv.org/abs/2610.14162
2. Stanford Scaling Intelligence. (2026, 12 de octubre). *Next-Concept Modeling: Fast, Parallel Coarse-to-Fine Text Generation*. https://scalingintelligence.stanford.edu/blogs/ncm/
3. ncm-mlx. (2026). *Running released Next-Concept Modeling checkpoints on Apple Silicon*. DEV Community. https://dev.to/janmusic/running-released-next-concept-modeling-checkpoints-on-apple-silicon-28mi
4. ncm-mlx-tinyworld. (2026). *A 5.0M-parameter next-concept generator, a 1.3M-parameter multiscale residual-VQ codec, and a same-size autoregressive baseline (4.8M)*. Hugging Face. https://huggingface.co/janmusic/ncm-mlx-tinyworld
5. MindStudio. (2026, 29 de octubre). *NCM vs LLMs: Independent Speed Benchmark Results Explained*. https://www.mindstudio.ai/blog/ncm-vs-llm-speed-benchmark-test
6. Liu, Y., Song, Y., Wang, Y., Ge, K., Lamb, A., Guo, Q., Chen, K., Zhou, B., & Lin, Z. (2026). *Next Concept Prediction in Discrete Latent Space Leads to Stronger Language Models*. arXiv:2602.08984. https://arxiv.org/abs/2602.08984
7. The NCP Team, Shanghai AI Lab & LUMIA Lab, Shanghai Jiao Tong University. (2026). *NCP-ArchPreview Technical Report*. arXiv:2609.10715. https://huggingface.co/papers/2609.10715
8. ByteDance Seed. (2026, 22 de octubre). *Cola2: Co-Adaptive Hierarchical Language Modeling with Continuous Semantic Compression and Balanced Discrete Generation*. arXiv:2610.31305. https://arxiv.org/abs/2610.31305
9. Williams, S., Waterman, A., & Patterson, D. (2009). Roofline: An Insightful Visual Performance Model for Multicore Architectures. *Communications of the ACM*, 52(4), 65–76.
10. Kwon, W., Li, Z., Zhuang, S., Sheng, Y., Zheng, L., Yu, C. H., Gonzalez, J. E., Zhang, H., & Stoica, I. (2023). *Efficient Memory Management for Large Language Model Serving with PagedAttention*. arXiv:2309.06180. https://arxiv.org/abs/2309.06180
11. NVIDIA. (2022). *NVIDIA H100 Tensor Core GPU Architecture*. Peak BF16/FP16 dense: 989 TFLOPS; HBM3 bandwidth: 3,35 TB/s; ridge point: ~295 FLOPs/Byte.
12. Eden AI. (2026, 20 de octubre). *NCM vs LLM: What Next-Concept Modeling Really Changes*. https://www.edenai.co
13. DEV Community. (2026, 26 de octubre). *NCM vs LLM: What Next-Concept Modeling Changes, and What It Doesn’t*. https://dev.to/senthil_kr/ncm-vs-llm-what-next-concept-modeling-changes-and-what-it-doesnt-33gj
14. Agarwal, M., Shah, S., Lee, C., Yoo, J., Huang, J., Hong, S., Raghunathan, A., Kim, J., & Boffi, N. M. (2026). *Posterior Refinement: Fast Language Generation via Any-Order Flow Maps*. arXiv:2606.24773. (Resultados de Sudoku FMLM+).

---

## Nota editorial de verificación (2026-11-08)

Este documento se incorpora como **referencia principal**, pero no todas sus
cifras tienen el mismo nivel de evidencia. Estado:

| Bloque | Estado | Evidencia / nota |
|---|---|---|
| NCM 10–31× vs DLMs; 4–5× menos tokens; Sudoku 86.1%; 725M | **Verificado** | arXiv:2610.14162, abstract, §4.3–§4.6, Tabla 3, Apéndice I. |
| NCM nunca comparó contra AR estándar en el paper | **Verificado** | El paper compara contra DLMs; el benchmark independiente cubre AR. |
| `ncm-mlx` fp64 3.2e-10 / 1.2e-13 | **Verificado** | `ncm-mlx/docs/official-checkpoints.md`: fila fp64; fp32 0.10 / 7.2e-5 es la ruta de producción. |
| `ncm-mlx` Sudoku 99.40 / 96.30 / 86.20 | **Verificado** | 1,988 / 1,926 / 1,724 de 2,000; paper 99.5 / 96.5 / 86.1. |
| `ncm-mlx-tinyworld` 5.0M/1.3M/4.8M, 89.8/98.6, 16.3/23.5, 6+1 vs 32 | **Verificado** | Model card `janmusic/NCM-TinyWorld-5M-MLX`. |
| NCP-ArchPreview 8.9B, 5.73T, 51.3%, +5.99 GSM8K | **Verificado** | arXiv:2609.10715. |
| Cola2 346B tokens, supera a Llama-3-8B solo en HellaSwag/StoryCloze | **Verificado con matiz** | Model card: 41.75 vs 39.21 y 80.42 vs 79.49; promedio global 60.10 vs 66.25. |
| Benchmark DGX Spark: ~4× single, ~2× resumen, AR gana en batch 64 | **Verificado (secundario)** | MindStudio, 29 Oct 2026; no es revisión por pares. |
| Cola2 arXiv `2610.xxxxx` | **Corregido** | arXiv:2610.31305. |
| Scaling Intelligence `/pubs/ncm/` | **Corregido** | URL usada: `https://scalingintelligence.stanford.edu/blogs/ncm/`. |
| \(M_{\text{KV}} \approx 19.3\) GB (Llama-3-8B, B=64, S=512, t=576) | **Revisar** | Con K+V y 2 bytes, el cálculo estándar da ~36.5 GB; el 19.3 GB parece omitir el factor 2 de K/V o usar otra convención. No citar sin reconciliar fórmula y número. |
| \(B^* \approx 3.5\) | **Dependiente del modelo** | Depende de TFLOPS efectivos, KV-cache, prefill y schedule; no es universal. |
| “NCM es directamente compute-bound” | **Matiz** | Los niveles tempranos (\(\ell_k\) pequeño) pueden ser memory-bound; el texto mismo lo corrige en §5.1. |
| “NCM listo para producción” | **No** | El documento concluye lo contrario; los sistemas en producción siguen en AR. |

### Corrección importante de una nota previa

Una nota anterior en `docs/references/ncm-critical-review.md` decía que la
paridad fp64 de `ncm-mlx` no estaba verificada. **Era incorrecta**: la
documentación completa de `ncm-mlx` sí incluye la fila fp64 con 3.2e-10
(TinyStories) y 1.2e-13 (Sudoku). La nota fue rectificada.
