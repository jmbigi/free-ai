# NCM vs AR bajo el modelo Roofline (referencia aportada)

> Documento de referencia aportado por el programador el 2026-11-08. Se conserva
> el texto original y se añade una sección de verificación. Las cifras de
> Roofline deben leerse con la precisión declarada; ver correcciones al final
> (regla 14).

---

# Análisis Roofline: NCM vs AR

El análisis bajo el **Modelo Roofline** permite matematizar por qué la generación autorregresiva (AR) y la no autorregresiva (NCM) operan en regímenes físicos radicalmente distintos dentro de una GPU moderna (por ejemplo, una NVIDIA H100 SXM).

El rendimiento efectivo ($P$, en TFLOPS) está acotado por dos restricciones de hardware:

$$\text{Performance} = \min \left( \text{Peak Compute (TFLOPS)}, \quad \text{Arithmetic Intensity} \times \text{Memory Bandwidth (GB/s)} \right)$$

Donde la **Intensidad Aritmética ($I$)** se define como la razón entre las operaciones de punto flotante realizadas y los bytes transferidos desde la memoria de alto ancho de banda (HBM) a la SRAM:

$$I = \frac{\text{FLOPs Totales}}{\text{Bytes Transferidos (HBM)}}$$

---

### 1. El régimen de AR ($B=1$): prisioneros del ancho de banda de memoria

Durante la fase de decodificación token a token de un modelo autorregresivo, el tamaño del lote es $1$ ($B=1$).

* **El cuello de botella:** Para generar un solo token, la GPU debe leer **todos los pesos del modelo ($P$ parámetros)** desde la HBM hacia los núcleos de procesamiento (SRAM) para realizar las multiplicaciones matriz-vector correspondientes.
* **Intensidad Aritmética en AR:**

$$I_{\text{AR}} \approx \frac{2 \times P}{P \times \text{bytes\_per\_param}} = \frac{2}{\text{bytes\_per\_param}}$$

Para un modelo en precisión FP16/BF16 ($\text{bytes\_per\_param} = 2$), la intensidad aritmética es de apenas **$1.0$ FLOP/byte**.
* **Diagnóstico Roofline:** En una H100 (cuyo *ridge point* —la intersección entre el límite de memoria y el de cómputo— se encuentra típicamente entre 15 y 50 FLOPs/byte según la precisión y arquitectura), un valor de $I = 1.0$ sitúa a AR profundamente a la izquierda del punto de inflexión. El modelo está **estrictamente limitado por el ancho de banda de memoria (*memory-bandwidth bound*)**. Los Tensor Cores de la H100 pasan más del 80-90% del tiempo inactivos, esperando que los datos de los pesos viajen por el bus de HBM.

---

### 2. El régimen de NCM: elevando la intensidad operacional

La Generación No Autorregresiva y basada en Enmascaramiento Continuo (NCM) altera esta ecuación al procesar bloques o múltiples niveles de refinamiento en paralelo.

* **El cambio estructural:** Aunque NCM ejecuta un número mayor de FLOPs totales por secuencia debido al reprocesamiento y los pases de refinamiento (`coarse-to-fine`), estos FLOPs se ejecutan en operaciones matriciales densas (multiplicaciones matriz-matriz, GEMM) en lugar de operaciones matriz-vector dispersas por cada token individual.
* **Intensidad Aritmética en NCM:** Al paralelizar la computación sobre múltiples posiciones espaciales o canales latentes simultáneamente dentro del mismo ciclo de carga de pesos, la reutilización de datos (*data reuse*) en SRAM aumenta drásticamente. La intensidad aritmética sube a valores cercanos a $10 - 30\text{ FLOPs/byte}$.
* **Diagnóstico Roofline:** NCM desplaza la operación hacia la derecha en el eje X del modelo Roofline, acercándose o superando el *ridge point*. Los Tensor Cores se saturan con trabajo útil. Por esta razón, **para solicitudes individuales ($B=1$), NCM es hasta $4\times$ más rápido**: aprovecha la capacidad de cómputo crudo de la GPU que AR desperdicia por estar limitado por el bus de memoria.

---

### 3. Matriz comparativa en el espacio Roofline

| Dimensión Analítica | AR ($B = 1$) | AR ($B = 64$) | NCM ($B = 1$) |
| --- | --- | --- | --- |
| **Forma Operacional** | Matriz-Vector (GEMV) | Matriz-Matriz (GEMM) | Matriz-Matriz Masiva (GEMM) |
| **Intensidad ($I$)** | Muy baja ($\approx 1$ FLOP/byte) | Alta ($\approx 64$ FLOPs/byte) | Moderada-Alta ($\approx 12 - 25$ FLOPs/byte) |
| **Cuello de Botella Físico** | Ancho de Banda HBM | Cómputo (Tensor Cores) | Cómputo / Lógica de Refinamiento |
| **Utilización de la GPU** | Ínfima (< 15%) | Óptima (> 80%) | Alta (> 60-70%) |

---

### 4. ¿Por qué ocurre la inversión en batch alto ($B=64$)?

Cuando aumentamos el tamaño del lote a $B=64$ en AR, el sistema agrupa las solicitudes. Los pesos del modelo se cargan una sola vez desde la HBM, pero se reutilizan para los 64 elementos del lote simultáneamente.

* Esto eleva artificialmente la intensidad aritmética efectiva de AR a $I_{\text{AR}} \approx 64 \times 1 = 64\text{ FLOPs/byte}$, empujando a AR a la meseta superior de cómputo del Roofline.
* En contraste, NCM realiza un volumen de cómputo total significativamente mayor ($\sum \ell_k \gg L$). Al escalar el lote a $B=64$, el costo computacional acumulado de los múltiples niveles de refinamiento de NCM satura la capacidad de los núcleos antes de que AR sufra el mismo estrangulamiento, provocando que el *throughput* de vLLM (gracias al *in-flight batching* y PagedAttention) supere al paradigma iterativo de NCM.

---

## Verificación y correcciones (2026-11-08)

### Especificaciones usadas

NVIDIA H100 SXM5 (datasheet/arquitectura):
- FP16/BF16 Tensor Core: **989 TFLOPS dense** (1,979 con sparsity 2:4).
- FP8 Tensor Core: 1,979 TFLOPS dense.
- TF32 Tensor Core: 494 TFLOPS dense.
- FP32 CUDA: ~67 TFLOPS.
- HBM3: **3.35 TB/s**.
- Ridge point = compute / bandwidth:
  - FP16/BF16 dense: **989 / 3.35 ≈ 295 FLOP/byte**.
  - FP8 dense: 1979 / 3.35 ≈ 591 FLOP/byte.
  - TF32 dense: 494 / 3.35 ≈ 148 FLOP/byte.
  - FP32 CUDA: 67 / 3.35 ≈ 20 FLOP/byte.

Fuente: NVIDIA H100 datasheet y Hopper architecture (ver enlaces al final).

### Correcciones al texto

1. **Ridge point “15–50 FLOPs/byte”**: es incorrecto para FP16/BF16 en H100 SXM. El valor correcto es **~295 FLOP/byte** (dense, sin sparsity). El rango 15–50 corresponde más bien a FP32/CUDA o a otras precisiones/arquitecturas; hay que declarar la precisión.
2. **“NCM = Enmascaramiento Continuo”**: NCM no es enmascaramiento continuo. Es generación **coarse-to-fine** con códigos discretos de un VQ-VAE multiescala; los niveles son secuenciales y las posiciones dentro de un nivel son paralelas. Corregir la terminología.
3. **“Todos los niveles en paralelo”**: solo las posiciones dentro de un nivel se predicen en paralelo; los niveles $k=1 \dots K$ son secuenciales.
4. **Intensidad NCM 10–30 FLOP/byte**: es una **estimación**, no una medición. Depende de $\ell_k$, del prefijo, del decoder VQ y de la implementación; los niveles coarse ($\ell_k$ pequeño) tienen baja reutilización. Medir con profiler/Nsight Compute.
5. **AR $B=64$ “meseta de cómputo”**: con FP16/BF16, $I \approx 64$ sigue por debajo del ridge ~295; AR mejora utilización pero no necesariamente satura Tensor Cores. La inversión medida a batch 64 (AR gana) es real, pero se explica por batching/PagedAttention y por el mayor cómputo total de NCM, no por una saturación perfecta.
6. **“NCM hasta 4× más rápido”**: el benchmark independiente reporta ~4× en traducción single-request y ~2× en resumen largo; no es universal. Citar el régimen y la tarea.
7. **Porcentajes de utilización GPU (<15%, >80%, >60–70%)**: son ilustrativos y no están respaldados por una medición citada; no presentarlos como resultados.
8. **“NCM B=1 aprovecha capacidad de cómputo que AR desperdicia”**: plausible como hipótesis Roofline, pero la medición independiente muestra que la ventaja depende de la tarea y del batch; no generalizar.
9. **NCM no hace streaming**: el texto no lo menciona; el benchmark independiente y el paper lo confirman. Cualquier comparación TTFT debe declarar que el primer nivel coarse no es texto usable.

### Referencias

- Williams, S., Waterman, A., & Patterson, D. (2009). *Roofline: An Insightful Visual Performance Model for Multicore Architectures.* Communications of the ACM. https://cacm.acm.org/research/roofline-an-insightful-visual-performance-model-for-multicore-architectures/
- NVIDIA H100 Tensor Core GPU datasheet: https://resources.nvidia.com/en-us-hopper-architecture/nvidia-tensor-core-gpu-datasheet
- NVIDIA Hopper architecture in-depth: https://developer.nvidia.com/blog/nvidia-hopper-architecture-in-depth/
- Kumbong et al., NCM, arXiv:2610.14162: https://arxiv.org/abs/2610.14162
- MindStudio, independent NCM vs LLM benchmark (29 Oct 2026): https://www.mindstudio.ai/blog/ncm-vs-llm-speed-benchmark-test
- Kwon et al., PagedAttention/vLLM, SOSP 2023.
