# NCM: revisión crítica aportada por el programador

> Documento de referencia aportado por el programador el 2026-11-08. Se conserva
> como material de trabajo. **No todo está verificado**: ver la sección final
> “Estado de verificación”. Las afirmaciones marcadas como no verificadas no
> deben citarse como evidencia del proyecto (regla 14 de `AGENTS.md`).

---

# Next-Concept Modeling (NCM): Investigación de Avances, Derivaciones y Evaluación Crítica

El análisis del paradigma *Next-Concept Modeling* (NCM) y sus extensiones se organiza en tres ejes: **evaluación de replicación y robustez**, **divergencia de paradigmas de predicción no atómica**, y una **evaluación crítica de su eficiencia computacional real**.

---

## 1. Replicación independiente y análisis de sensibilidad

La validación de arquitecturas de generación jerárquica no autorregresiva requiere separar la capacidad expresiva de la arquitectura frente a la heurística de optimización.

### 1.1 Implementación `ncm-mlx` (Apple Silicon)

El puerto independiente `ncm-mlx` tradujo la arquitectura del generador e inferencia jerárquica a la infraestructura de MLX, aportando los siguientes hallazgos:

#### Consistencia de Reconstrucción Discreta

En precisión de coma flotante de 64 bits (`fp64`), la diferencia absoluta máxima de logits ($\max \vert{}z_{\text{MLX}} - z_{\text{PyTorch}}\vert{}$) entre los *checkpoints* oficiales de PyTorch y el puerto MLX fue de $3.2 \times 10^{-10}$ en el conjunto *TinyStories* y $1.2 \times 10^{-13}$ en *Sudoku*. Esto confirma que las transformaciones lineales y las proyecciones del VQ-VAE multiescala fueron implementadas sin sesgos de decodificación.

#### Sensibilidad a la Optimizabilidad (Entrenamiento *Scratch*)

Al reentrenar un modelo reducido en Sudoku desde una inicialización aleatoria (semillas 0 y 1), la tasa de resolución exacta (*exact match*) en dificultad "difícil" cayó del **86.1%** (checkpoint oficial) a **40.30%** y **33.25%** respectivamente.

```
Tasa de resolución Sudoku (Difícil)
├── Checkpoint Oficial (PyTorch): 86.10% [====================]
├── MLX (Replicación Checkpoint): 86.20% [====================]
├── MLX (Scratch - Semilla 0):     40.30% [========]
└── MLX (Scratch - Semilla 1):     33.25% [=======]

```

Esto demuestra la presencia de una **superficie de pérdida no convexa altamente patológica** en la optimización conjunta de cuantizadores vectoriales residuales (RVQ) con el generador jerárquico. La ventaja funcional de NCM no se deduce solo de la arquitectura, sino del balance entre el *annealing* del libro de códigos (*codebook*) y la tasa de aprendizaje del *backbone*.

---

## 2. Taxonomía Teórica y Divergencia de Paradigmas

El objetivo fundamental de NCM es descomponer la verosimilitud conjunta $P(X)$ mediante una jerarquía de representaciones discretas en lugar de la descomposición autorregresiva estándar paso a paso.

$$\text{Estándar (AR): } P(X) = \prod_{t=1}^L P(x_t \mid x_{<t})$$

$$\text{NCM (Jerárquico): } P(X) = \prod_{k=1}^K P(C^{(k)} \mid C^{(<k)})$$

Donde $C^{(k)} = \{c_1^{(k)}, c_2^{(k)}, \dots, c_{\ell_k}^{(k)}\}$ representa el conjunto de códigos discretos del nivel jerárquico $k$, con $\vert{}C^{(k)}\vert{} = \ell_k \ll L$ para niveles iniciales ($k \ll K$).

```
[Nivel Coarse c(1)]   (16 tokens equivalents)  --> Visión Global / Plan
        │
        ▼
[Nivel Mid    c(2)]   (64 tokens equivalents)  --> Estructura Sintáctica
        │
        ▼
[Nivel Fine   c(3)]   (256 tokens equivalents) --> Detalle Léxico / Tokens

```

### 2.1 Comparación Arquitectónica de las Tres Rutas

1. **Ruta 1: NCM (Stanford / Together AI)**
* **Mecánica:** Cuantización Vectorial Residual (RVQ) multiescala. El Transformer predice simultáneamente en el paso $k$ todos los elementos de $C^{(k)}$ usando atención cruzada sobre las reconstrucciones de los niveles $1 \dots k-1$.
* **Decodificación:** $K$ pasos forward secuenciales independientemente de la longitud final $L$.


2. **Ruta 2: ConceptLM / NCP (Shanghai AI Lab)**
* **Mecánica:** Mantiene la decodificación token-a-token pero incluye una pérdida auxiliar de predicción de conceptos futuros $\mathcal{L}_{\text{NCP}}$ basada en agrupamiento latente (*k-means* o *VQ* sobre estados ocultos profundos).
* **Formulación de Pérdida:** $\mathcal{L}_{\text{total}} = \mathcal{L}_{\text{NTP}} + \lambda \mathcal{L}_{\text{NCP}}$, donde $\mathcal{L}_{\text{NCP}} = -\sum_{t} \log P(c_{t+\Delta} \mid x_{\le t})$.


3. **Ruta 3: Cola2 (ByteDance)**
* **Mecánica:** Generación en espacio latente continuo sin discretizar. Utiliza un *Variational Autoencoder* (VAE) con compresión temporal para generar agregados semánticos mediante un *Diffusion Transformer* (DiT).
* **Ventaja:** Evita el problema del colapso del libro de códigos (*codebook collapse*) inherentemente asociado a los cuantizadores discretos como RVQ.

---

### 2.2 Cuadro Comparativo de Paradigmas

| Dimensión Técnica | **NCM** (Generación Jerárquica Discreta) | **ConceptLM / NCP** (Supervisión Auxiliar) | **Cola2** (Latente Continuo / DiT) |
| --- | --- | --- | --- |
| **Representación Latente** | Discreta (Residual VQ-VAE) | Discreta (Clustered Hidden States) | Continua (Variational Latent Vectors) |
| **Pasos de Inferencia ($NFE$)** | Fijo: $K$ pasos ($K \ll L$) | Variables: $L$ pasos (Autorregresivo) | Intermedio: Pasos del Sampler de Difusión |
| **Complejidad de Atención** | $\mathcal{O}(K \cdot \ell_K^2)$ | $\mathcal{O}(L^2)$ | $\mathcal{O}(M^2)$ donde $M$ es el total de *spans* |
| **Colapso de Representación** | Sensible al *Codebook Perplexity* | No crítico (los tokens guían) | Mitigado vía KL-regularización continua |
| **Escala Comprobada** | $\le 725\text{M}$ Parámetros | **8.9B** Parámetros (5.73T tokens) | Checkpoints empíricos ~346B tokens |

---

## 3. Evaluación Crítica: Rendimiento y Costo Computacional

Para analizar la viabilidad comercial y técnica de NCM frente a modelos autorregresivos (AR) con depuración de memoria (*KV-Cache*), es necesario evaluar la compleijdad teórica de operaciones en coma flotante (FLOPs).

### 3.1 FLOPs de Inferencia: Latencia vs. Throughput

Sea $N$ el número de parámetros del modelo, $L$ la longitud total de la secuencia, y $K$ el número de niveles jerárquicos de NCM.

* **Modelo Autorregresivo (AR) con KV-Cache:**
En cada paso de generación, la proyección $QKV$ y las capas Feed-Forward Network (FFN) computan sobre un solo token ($1$).
$$\text{FLOPs}_{\text{AR}} \approx 2N \cdot L + \mathcal{O}(L^2 \cdot d_{\text{model}})$$


* **NCM (Next-Concept Modeling):**
En cada nivel $k$, el Transformer procesa la secuencia proyectada completa de longitud $\ell_k$. Si asumimos niveles de resolución ascendente ($\ell_1 < \ell_2 < \dots < \ell_K = L$):
$$\text{FLOPs}_{\text{NCM}} \approx 2N \cdot \sum_{k=1}^K \ell_k + \mathcal{O}\left( \sum_{k=1}^K \ell_k^2 \cdot d_{\text{model}} \right)$$



#### Implicación en Servidores de Alta Concurrencia

Si $\sum_{k=1}^K \ell_k > L$, **NCM computa formalmente más FLOPs globales que un modelo autorregresivo** para producir la misma secuencia.

```
Régimen de Procesamiento:
├── Single-Request (Batch Size = 1):
│   └── NCM es superior en latencia (reducido NFE limita accesos a memoria VRAM).
└── Batched Serving (Continuous Batching, Batch Size >= 32):
    └── El modelo Autorregresivo tradicional (AR) logra mayor throughput por WATT
        al saturar Compute Cores mediante KV-Caching optimizado (vLLM/FlashAttention).

```

### 3.2 Limitaciones de la Jerarquía Fija

NCM asigna la misma estructura jerárquica $K$ a cualquier secuencia. Esto genera dos ineficiencias:

1. **Sub-utilización:** Textos simples o deterministas (ej. respuestas "Sí/No") requieren computar todos los $K$ niveles jerárquicos.
2. **Sobre-compresión:** Textos con alta densidad de información (código fuente o razonamiento matemático paso a paso) sufren pérdidas en los niveles iniciales de baja resolución ($\ell_1$), propagando errores irrecuperables en las capas posteriores.

---

## 4. Preguntas Abiertas e Investigaciones Futuras

1. **Adaptabilidad Dinámica de Niveles:** ¿Es posible implementar un mecanismo de parada temprana (*early exit*) en el árbol de decodificación discreto para secuencias de baja entropía?
2. **Co-Entrenamiento End-to-End:** Reducir la degradación de calidad eliminando el entrenamiento desacoplado del VQ-VAE mediante pérdidas diferenciables (ej. *Gumbel-Softmax* o *Straight-Through Estimators* alineados con la pérdida del generador).
3. **Decodificación Especulativa Multinivel:** Utilizar los niveles iniciales de NCM ($c^{(1)}, c^{(2)}$) como un *draft model* ultra-rápido para guiar un modelo autorregresivo estándar que actúe como verificador en paralelo.

---

## 5. Referencias Teóricas y Empíricas

1. **Van den Oord, A., Vinyals, O., & Kavukcuoglu, K. (2017).** *Neural Discrete Representation Learning.* Advances in Neural Information Processing Systems (NeurIPS). *(Fundamento de VQ-VAE y cuantización vectorial)*.
2. **Zheng, L., et al. (2024).** *Discrete Hierarchical Modeling for Non-Autoregressive Generation.* Journal of Machine Learning Research (JMLR). *(Análisis formal de decodificación por bloques latentes)*.
3. **Kwon, W., et al. (2023).** *Efficient Memory Management for Large Language Model Serving with PagedAttention.* Proceedings of the ACM SIGSYS Symposium on Operating Systems Principles (SOSP). *(Base técnica sobre los límites de batching en modelos AR frente a arquitecturas sin KV-cache tradicional)*.
4. **Apple MLX Software Architecture (2023).** *Out-of-Core Execution and Numerical Parity on Apple Silicon Graphics Hardware.* Apple Machine Learning Research.

---

## Estado de verificación (2026-11-08)

| Afirmación | Estado | Evidencia / nota |
|---|---|---|
| `ncm-mlx` existe y es un puerto independiente de NCM a MLX | **Verificado** | https://github.com/janmus1c/ncm-mlx |
| Paridad fp64 con diferencias 3.2e-10 / 1.2e-13 | **Verificado** | `ncm-mlx/docs/official-checkpoints.md`: fila fp64 **3.2e-10** (TinyStories) y **1.2e-13** (Sudoku-easy). La ruta fp32 reporta 0.10 (1.2e-4 relativa) y 7.2e-5; ambas son consistentes. |
| Sudoku MLX 99.40 / 96.30 / 86.20 | **Verificado** | `ncm-mlx`: 1,988/2,000 easy, 1,926/2,000 medium, 1,724/2,000 hard; coincide con el paper dentro de 0.1–0.2 pts. |
| Sudoku scratch difíciles 40.30% / 33.25% | **Parcialmente verificado** | La model card `janmusic/ncm-mlx-sudoku` cita 33.25–40.30% “with different model size and training”; no es una replicación limpia del checkpoint oficial. |
| NCM paper: 21×/10×/31×; 4–5× menos tokens; Sudoku 86.1/81.3/1 | **Verificado** | arXiv:2610.14162, abstract, §4.4 Tabla 3, §4.6. |
| Sudoku depende de estrategia de decodificación | **Verificado por benchmark independiente** | MindStudio, 29 Oct 2026; un DLM con orden por confianza se acerca. |
| NCM sin streaming real / longitud fija / task-specific | **Verificado** | Paper Apéndice I; benchmark independiente. |
| NCM batch 64: AR gana | **Verificado por benchmark independiente** | MindStudio, 29 Oct 2026. El texto original dice “batch >= 32”; la medición citada es batch 64. |
| ConceptLM 13 benchmarks, 70M–1.5B, 300B tokens | **Verificado** | arXiv:2602.08984. |
| “ConceptLM 8.9B” en la tabla | **Corrección** | 8.9B corresponde a **NCP-ArchPreview**, no a ConceptLM (este llega a 1.5B; el continual pretraining usa un Llama 8B). |
| NCP-ArchPreview 8.9B, 5.73T tokens, 51.3%, +2.45 | **Verificado** | arXiv:2609.10715. |
| Cola2 346B tokens, 60.10 en 8 tareas | **Verificado** | Model card ByteDance-Seed/Cola2; 346.03B tokens, ~9B params. La tabla del texto mezcla “346B tokens” con “escala”; no son parámetros. |
| Cola2 supera a Llama-3-8B solo en HellaSwag/StoryCloze | **Verificado** | Model card: 41.75 vs 39.21 y 80.42 vs 79.49; promedio global 60.10 vs 66.25. |
| Fórmulas FLOPs y complejidad O(K·ℓ_K²) | **Aproximación, no teorema** | Dependen de prefijo, atención por nivel y decoder; el texto las presenta como estimaciones. No usar como cota exacta. |
| “Zheng et al. 2024 JMLR, Discrete Hierarchical Modeling…” | **No encontrado** | No se localizó esa referencia en JMLR/arXiv con esos datos. Marcar como no verificada. |
| “Apple MLX 2023, Out-of-Core Execution and Numerical Parity…” | **No encontrado** | No se localizó ese documento de Apple. Marcar como no verificada. |
| Van den Oord 2017 / Kwon 2023 PagedAttention | **Verificables** | Referencias conocidas; el texto tiene una errata: “ACM SIGSYS” debe ser **SOSP**. |

### Correcciones concretas al texto

1. `ncm-mlx` reporta paridad **fp32 y fp64**: fp64 3.2e-10/1.2e-13 (verificado); fp32 0.10/7.2e-5 es la ruta de producción, no una contradicción. La corrección anterior de este documento era errónea y queda rectificada.
2. El 8.9B es **NCP-ArchPreview**, no ConceptLM.
3. Cola2 tiene ~9B parámetros y **346.03B tokens de entrenamiento**; no “346B de escala” de parámetros.
4. La ventaja de batching se midió en **batch 64**, no en “>=32”.
5. Las fórmulas FLOPs son estimaciones; no una demostración formal.
6. “SIGSYS” → **SOSP** en la referencia de PagedAttention.
7. Las referencias Zheng 2024 y Apple MLX 2023 no se localizaron; no usarlas como evidencia hasta verificarlas.
