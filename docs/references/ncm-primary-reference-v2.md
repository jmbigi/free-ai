# Next-Concept Modeling (NCM): análisis técnico, evaluación experimental y comparación con las nuevas arquitecturas de lenguaje

**Informe técnico y crítico — Versión final 2.0**
**Fecha de revisión:** 8 de noviembre de 2026
**Ámbito:** Arquitecturas de generación de lenguaje, eficiencia de inferencia, entrenamiento, benchmarks y escalabilidad.
**Metodología:** Revisión bibliográfica, contraste de resultados publicados, replicaciones independientes y análisis matemático de rendimiento GPU.

> **Referencia principal del proyecto (v2).** Documento aportado por el
> programador. Sustituye a `ncm-primary-reference.md` (v1), que queda como
> histórico. Se aplicaron tres correcciones factuales señaladas en la nota
> editorial final: TF32 dense/sparse, orden aprendido en Sudoku y alcance real
> de la comparación NCM vs AR. Las cifras de KV-cache y prefill de la v1
> quedan reemplazadas por las de esta versión.

---

# 1. Crítica metodológica profunda

## 1.1. Introducción y alcance de la evaluación

Next-Concept Modeling (NCM) propone una alternativa a la generación autorregresiva tradicional mediante una representación jerárquica del texto y una estrategia de generación coarse-to-fine.

Su principal innovación consiste en generar representaciones progresivamente más detalladas, en lugar de producir un token después de otro. Un tokenizador multiscala basado en residual VQ-VAE codifica el texto en una jerarquía de códigos discretos, y un transformer genera esos niveles de forma progresiva, prediciendo todos los códigos de un nivel en paralelo.

El trabajo original presenta resultados prometedores:

- Entre 10 y 31 veces más velocidad frente a determinados modelos de difusión de lenguaje.
- Aproximadamente 4–5 veces menos posiciones de entrenamiento procesadas.
- Resultados competitivos en generación de texto y resumen.
- Mejor rendimiento que los baselines autorregresivos y de difusión evaluados en Sudoku.

Sin embargo, estos resultados no demuestran automáticamente que NCM sea superior a los transformers autorregresivos en aplicaciones de producción. Para evaluar correctamente la arquitectura es necesario distinguir cinco dimensiones: calidad de generación, latencia de una solicitud individual, throughput bajo concurrencia, eficiencia de entrenamiento, y escalabilidad y reproducibilidad.

## 1.2. Limitaciones del diseño experimental original

La primera cuestión es identificar exactamente qué se comparó.

El artículo original evalúa NCM frente a modelos de difusión de lenguaje (DLMs) en sus experimentos principales de generación y eficiencia, especialmente LM1B, OpenWebText y XSum. En Sudoku también incorpora baselines autorregresivos (AR) y de difusión.

Por tanto, sería incorrecto afirmar que el artículo nunca compara NCM con AR. Lo que no presenta es una evaluación sistemática de serving contra un transformer AR estándar, con idénticas condiciones de hardware, longitud de contexto, calidad, batching y concurrencia.

Los resultados de velocidad publicados son:

| Benchmark | Comparación | Resultado |
|---|---|---|
| LM1B | NCM frente a DUO | 21× más rápido |
| OpenWebText | NCM frente a modelos de difusión | 10× más rápido |
| XSum | NCM frente a AURORA-LM | 31× más rápido |
| Sudoku difícil | NCM frente a FMLM+ | 86,1% frente a 81,3% |

Los resultados de LM1B y XSum corresponden a protocolos experimentales concretos. El paper mide 1.024 secuencias con batch 16 en una NVIDIA H100 SXM de 80 GB. No deben interpretarse como aceleraciones universales frente a cualquier LLM.

**Problema metodológico:** falta una comparación integral que incluya NCM frente a Llama o Qwen autorregresivos, igualdad de parámetros y precisión numérica, igualdad de calidad de salida, prefill y decode, batch 1 a 128, latencia p50/p95/p99, throughput, consumo de memoria y energía, y coste de servir una cantidad equivalente de solicitudes. La comparación con un DLM no sustituye esta evaluación.

### Evidencia independiente

El 29 de octubre de 2026, MindStudio publicó una evaluación adicional realizada sobre DGX Spark. Sus resultados indican aproximadamente 4× más velocidad para NCM en determinadas solicitudes individuales frente a un AR emparejado, aproximadamente 2× en determinados escenarios de resumen, ventaja del AR al alcanzar batch 64, y una posible ventaja importante del orden de decodificación en Sudoku.

Es una evidencia interesante, pero debe tratarse como un benchmark independiente publicado por una empresa, no como una replicación académica revisada por pares. No permite establecer un punto de cruce universal para cualquier GPU o modelo.

**Conclusión correcta:** la ventaja de NCM depende del régimen de inferencia y necesita una evaluación de serving más amplia.

## 1.3. Errores y limitaciones del modelo analítico Roofline/FLOPs

El modelo de rendimiento debe distinguir entre operaciones matemáticas, tráfico de memoria y tiempo efectivo de ejecución.

### Error 1. Utilizar únicamente la suma de longitudes para justificar el coste cuadrático

La afirmación de que \(\sum_k \ell_k \gg L\) implica \(F_{\mathrm{NCM}}>F_{\mathrm{AR}}\) no constituye una demostración matemática. La suma de longitudes determina principalmente los términos lineales del coste. Para justificar el componente cuadrático es necesario estudiar \(\sum_k \ell_k^2\).

En un schedule geométrico de razón 2, aproximando las longitudes como \(\ell_k \in \{1,2,4,\ldots,L\}\), se obtiene \(\sum_k \ell_k \approx 2L\) y \(\sum_k \ell_k^2 \approx \frac{4}{3}L^2\). Por otra parte, la atención autorregresiva con KV-cache tiene un coste acumulado que depende de \(\sum_{t=1}^{L}(S+t) = LS+\frac{L(L+1)}{2}\), donde \(S\) es la longitud del prompt, \(L\) es la cantidad de tokens generados y \(\ell_k\) es la longitud de cada nivel de NCM.

Esto permite identificar una posible diferencia de coste, pero no determina por sí solo el tiempo de ejecución. Es necesario incorporar las dimensiones reales de los tensores, las máscaras de atención, el uso de caché y la eficiencia de los kernels.

### Error 2. Modelar AR sin KV-cache

Una aproximación basada exclusivamente en el tamaño de los pesos (\(M_{\mathrm{weights}}=P\cdot b\)) es insuficiente. El tráfico de memoria de un modelo autorregresivo incluye pesos del modelo, KV-cache, activaciones, buffers temporales y transferencias adicionales.

Para un modelo con atención GQA, la memoria del KV-cache puede aproximarse mediante:

\[
M_{\mathrm{KV}}=
B\cdot 2N_{\mathrm{layers}}
\cdot N_{\mathrm{KVheads}}
\cdot d_{\mathrm{head}}
\cdot (S+t)
\cdot b_{\mathrm{KV}}
\]

Donde \(B\) es el batch, \(N_{\mathrm{layers}}\) el número de capas, \(N_{\mathrm{KVheads}}\) las cabezas KV, \(d_{\mathrm{head}}\) la dimensión de cada cabeza, \(S+t\) la longitud total de la secuencia y \(b_{\mathrm{KV}}\) los bytes por elemento.

En Llama 3 8B, los parámetros son 32 capas, 32 cabezas de atención, 8 cabezas KV, dimensión oculta de 4.096 y dimensión por cabeza de 128. Para BF16, con \(S=512\), \(t=576\) y \(B=64\), obtenemos \(M_{\mathrm{KV}}\approx 9,13\ \text{GB}\). Para batch 128, \(M_{\mathrm{KV}}\approx 18,25\ \text{GB}\).

**Corrección importante:** utilizar directamente la dimensión oculta de 4.096 en lugar de la dimensión KV de 1.024 (8 cabezas × 128) sobreestima el tamaño de esta caché cuatro veces.

Además, el tamaño del KV-cache no equivale automáticamente al tráfico HBM por solicitud. Para calcular el tráfico real es necesario conocer cuántas veces se lee, qué permanece en caché y cómo se agrupan las operaciones.

### Error 3. Considerar NCM compute-bound desde batch 1

NCM realiza operaciones paralelas sobre bloques de diferente tamaño, pero esto no significa que todos sus niveles estén limitados por capacidad de cálculo. Los niveles pequeños pueden presentar baja ocupación de GPU, lanzamientos de kernels poco eficientes, costes de memoria relativamente elevados, sobrecarga de sincronización y baja utilización de Tensor Cores.

Por tanto, no es correcto utilizar una única aproximación \(T_{\mathrm{NCM}} = \frac{B\cdot F_{\mathrm{gen}}}{\mathrm{TFLOPS}}\) para todos los tamaños de batch. El rendimiento debe modelarse por nivel:

\[
T_{\mathrm{NCM}}
\approx
\sum_{k=1}^{K}
\max\left(
\frac{F_k}{C_{\mathrm{eff},k}},
\frac{M_k}{BW_{\mathrm{eff},k}}
\right)
+
T_{\mathrm{overhead}}
\]

Donde \(F_k\) son los FLOPs del nivel, \(C_{\mathrm{eff},k}\) la capacidad de cálculo efectiva, \(M_k\) el tráfico de memoria, \(BW_{\mathrm{eff},k}\) el ancho de banda efectivo y \(T_{\mathrm{overhead}}\) los lanzamientos, sincronización y operaciones auxiliares. Es una aproximación Roofline, no un modelo exacto de ejecución.

### Error 4. Suponer que el coste de atención se puede reducir mediante caché sin verificar la implementación

El cálculo \(F_{\mathrm{gen}}^{\mathrm{NCM}} \propto \sum_k(S+\ell_k)^2\) puede sobreestimar el coste si una implementación reutiliza resultados de atención entre niveles. Pero tampoco puede asumirse que esa reutilización es gratuita o que resulta directamente compatible con la arquitectura.

Hay que verificar qué tensores permanecen invariantes, qué representaciones cambian entre niveles, qué máscaras de atención utiliza cada nivel, si los estados KV pueden reutilizarse correctamente y qué coste adicional introduce la reconstrucción de representaciones. Por ello, no se conserva la estimación anterior de 541 GFLOPs ni el supuesto ahorro del 48% para XSum como resultados demostrados.

### Error 5. Confundir TFLOPS máximos con rendimiento efectivo

La H100 SXM presenta las siguientes especificaciones:

| Métrica | Valor |
|---|---:|
| Memoria HBM | 80 GB |
| Ancho de banda HBM | 3,35 TB/s |
| BF16 denso | 989 TFLOPS |
| BF16 con sparsity estructurada | 1.979 TFLOPS |
| TF32 Tensor Core denso | 494 TFLOPS |
| TF32 Tensor Core con sparsity | 989 TFLOPS |

Los valores de 989 TFLOPS para BF16 denso y 1.979 TFLOPS para BF16 con sparsity están confirmados en las especificaciones oficiales de NVIDIA y en bases de datos de hardware. La diferencia es fundamental: el valor de 1.979 TFLOPS incorpora sparsity estructurada y no debe utilizarse como rendimiento denso convencional. Lo mismo ocurre con TF32: 989 TFLOPS corresponde a sparsity; el valor denso es 494 TFLOPS.

El rendimiento efectivo depende del tamaño de matrices, el batch, la precisión, el kernel utilizado, la ocupación, los accesos a memoria y la eficiencia de Tensor Cores. Utilizar directamente el máximo teórico puede generar predicciones muy alejadas del comportamiento real.

### Error 6. Despreciar el prefill

El prefill no debe eliminarse del modelo de latencia. Para un transformer de 8.000 millones de parámetros y un prompt de 512 tokens, una aproximación del coste lineal de proyecciones es:

\[
F_{\mathrm{prefill}}\approx 2PS
\approx 2\cdot8\cdot10^9\cdot512
\approx8.192\ \text{TFLOPs}
\]

Con 989 TFLOPS teóricos: \(T_{\mathrm{prefill,min}}\approx8,3\ \text{ms}\). Es un límite inferior simplificado, no una predicción de latencia real. Excluye otros componentes del modelo. Una estimación anterior de 133 μs no es coherente con el coste completo de las proyecciones de un modelo de 8B para ese prompt.

## 1.4. El error de utilizar Roofline como predictor directo de throughput

El modelo Roofline es útil para identificar límites de rendimiento, pero no es un simulador completo de serving. Su formulación básica es:

\[
P_{\mathrm{attainable}} = \min(P_{\mathrm{peak}}, I\cdot BW)
\]

Donde \(P_{\mathrm{peak}}\) es la capacidad máxima de cálculo, \(I\) la intensidad aritmética y \(BW\) el ancho de banda de memoria.

El punto de equilibrio de la H100 SXM, utilizando BF16 denso, es:

\[
I_{\mathrm{ridge}} = \frac{989}{3,35} \approx 295\ \text{FLOPs/Byte}
\]

Este valor está confirmado de forma independiente en la literatura sobre Roofline para H100.

Para una multiplicación equivalente a \((128,4096)\times(4096,11008)\), la intensidad aritmética aproximada es de 122 FLOPs/Byte, considerando BF16 y los principales accesos a matrices. Por tanto, \(122<295\): el kernel queda por debajo del ridge point y es memory-bound en el modelo Roofline ideal.

Esto no significa que cualquier ejecución real presente exactamente ese comportamiento: las cachés, las fusiones de operaciones y las características del kernel pueden modificar el resultado. Tampoco existe una regla general de que \(\mu>0,3\) implique compute-bound. Una fracción de utilización no equivale a intensidad aritmética.

## 1.5. Problemas del script `profile_h100_roofline.py`

El script propuesto no debe considerarse un instrumento válido para determinar la saturación HBM sin modificaciones. Los principales problemas son:

**1. Memoria asignada frente a tráfico HBM.** Las métricas de memoria del profiler de PyTorch no representan automáticamente los bytes transferidos entre HBM y GPU. Un cambio neto de memoria asignada puede ser prácticamente cero aunque un kernel lea repetidamente los pesos desde memoria.

**2. Cobertura incompleta de FLOPs.** `with_flops=True` utiliza fórmulas registradas para determinados operadores. Los kernels personalizados y las operaciones fusionadas no tienen necesariamente una contabilización completa.

**3. Agregación de tiempos.** `key_averages()` agrupa eventos por operador. Sumar indiscriminadamente tiempos de eventos relacionados puede introducir solapamientos o interpretaciones incorrectas del tiempo acumulado. Conviene utilizar tiempos propios de dispositivo, trazas de ejecución y mediciones sincronizadas.

**4. Comparación de kernels aislados.** Comparar una operación GEMV con una GEMM no permite demostrar la superioridad de una arquitectura completa. Para ello se necesita ejecutar los modelos completos con el mismo workload.

**5. Métricas de memoria insuficientes.** Para medir tráfico HBM se recomienda utilizar NVIDIA Nsight Compute y sus métricas de memoria DRAM, por ejemplo `dram__bytes_read.sum`, `dram__bytes_write.sum`, throughput DRAM, porcentaje de utilización de memoria, y métricas de ocupación y Tensor Cores.

## 1.6. La falacia de la cancelación de errores

El modelo original mezcla aproximaciones que pueden introducir sesgos en direcciones opuestas.

| Simplificación | Consecuencia potencial |
|---|---|
| Omitir tráfico KV | Subestimar el coste de memoria de AR |
| Utilizar TFLOPS máximos | Subestimar el tiempo de ejecución |
| Ignorar prefill | Subestimar la latencia total |
| Sobreestimar el coste de atención NCM | Sobrestimar su tiempo |
| Ignorar lanzamientos y sincronización | Subestimar el tiempo real |
| Ignorar la reutilización de pesos por batch | Distorsionar el throughput |

El problema es que algunos errores pueden compensarse. Un resultado numérico aparentemente razonable no demuestra que el modelo sea correcto. La validez exige que cada componente esté justificado independientemente y que las predicciones coincidan con mediciones reales.

## 1.7. Sudoku: separar arquitectura y orden de decodificación

Uno de los resultados más llamativos de NCM es su rendimiento en Sudoku. El artículo original presenta:

| Modelo | Sudoku fácil | Sudoku medio | Sudoku difícil |
|---|---:|---:|---:|
| AR | 14,6% | 5,1% | 1,0% |
| DUO | 96,3% | 84,7% | 58,4% |
| FMLM+ | 97,7% | 92,8% | 81,3% |
| NCM | 99,5% | 96,5% | 86,1% |

NCM presenta una ventaja clara sobre los baselines evaluados. Sin embargo, es necesario considerar una variable adicional: el orden de generación.

En Sudoku, una estrategia que permite revisar y corregir las celdas anteriores puede tener una ventaja importante sobre una estrategia estrictamente secuencial. NCM genera representaciones progresivamente más completas y permite modificar resultados previos. Una evaluación independiente publicada por MindStudio sostiene que un modelo de difusión emparejado puede aproximarse a estos resultados utilizando un orden de llenado basado en confianza.

La literatura sobre decodificación en modelos de difusión de lenguaje respalda esta preocupación. PONDER (arXiv:2610.23531) reporta que un **orden de generación aprendido** eleva la precisión en Sudoku visual difícil de **3,9% a 56,6%**, frente a **38,7%** con el orden greedy basado en incertidumbre (SRM). Para aislar la contribución arquitectónica se necesita un experimento factorial que controle arquitectura y orden de decodificación de forma independiente:

| Experimento | Arquitectura | Orden |
|---|---|---|
| A | AR | Izquierda a derecha |
| B | AR con revisión | Orden de confianza |
| C | Difusión | Orden aleatorio |
| D | Difusión | Orden de confianza |
| E | NCM | Coarse-to-fine |

Todos deben utilizar el mismo conjunto de tableros, el mismo presupuesto de entrenamiento, tamaños de modelo comparables, igual presupuesto de inferencia, múltiples semillas, y métricas de solución completa y validez de restricciones.

La pregunta correcta no es si NCM resuelve Sudoku mejor que AR, sino cuánto de esa mejora corresponde a la arquitectura y cuánto al procedimiento de decodificación.

## 1.8. Tabla consolidada de problemas metodológicos

| # | Problema | Gravedad | Acción correctiva |
|---|---|---|---|
| 1 | Comparación de serving incompleta | Alta | Benchmark AR equivalente |
| 2 | KV-cache mal dimensionado | Alta | Incorporar GQA |
| 3 | Modelo Roofline simplificado | Alta | Modelar cada nivel |
| 4 | TFLOPS máximos como rendimiento real | Alta | Medir rendimiento efectivo |
| 5 | Prefill despreciado | Media-alta | Incluir latencia completa |
| 6 | Tráfico HBM mal medido | Crítica | Utilizar Nsight Compute |
| 7 | Agregación incorrecta de tiempos | Alta | Analizar trazas y tiempos propios |
| 8 | Orden Sudoku no controlado | Alta | Experimentos factoriales |
| 9 | Reutilización de caché no demostrada | Media | Verificar implementación |
| 10 | Generalización a modelos grandes | Alta | Evaluación a escala superior |

**Veredicto metodológico:** NCM presenta resultados experimentales interesantes y una arquitectura diferenciada, pero todavía no existe evidencia suficiente para establecer su superioridad general frente a transformers autorregresivos en serving.

---

# 2. Resumen ejecutivo

## Next-Concept Modeling: una alternativa a la generación token a token

Next-Concept Modeling (NCM), desarrollado por investigadores de Hazy Research de Stanford y colaboradores de Together AI, introduce una estrategia jerárquica de generación de texto.

En lugar de predecir un token después de otro, utiliza un tokenizador multiscala basado en residual VQ-VAE que representa el texto mediante diferentes niveles de códigos discretos. Un transformer genera esos niveles progresivamente: primero produce una representación general y posteriormente incorpora detalles hasta reconstruir el texto final. La generación se realiza en K etapas, con predicción paralela dentro de cada nivel.

### Resultados principales

El trabajo original presenta los siguientes resultados:

| Dimensión | Resultado |
|---|---|
| Velocidad en LM1B | 21× frente a DUO |
| Velocidad en OpenWebText | 10× frente a DLM |
| Velocidad en XSum | 31× frente a AURORA-LM |
| Entrenamiento LM1B | 13,36B frente a 66B posiciones |
| Eficiencia de entrenamiento | 4,9× menos posiciones |
| Sudoku difícil | 86,1% |
| Escala máxima estudiada | 725M parámetros |

Los speedups corresponden a las comparaciones y condiciones concretas del artículo, no a comparaciones universales contra LLM autorregresivos.

### Reproducibilidad

La implementación independiente `ncm-mlx` ha conseguido ejecutar checkpoints oficiales y reproducir resultados de Sudoku muy próximos a los publicados.

En las pruebas publicadas:

| Dificultad | Paper original | Replicación MLX |
|---|---:|---:|
| Fácil | 99,5% | 99,40% |
| Media | 96,5% | 96,30% |
| Difícil | 86,1% | 86,20% |

Sin embargo, los experimentos de entrenamiento independiente desde cero presentan resultados inferiores:

| Semilla | Fácil | Media | Difícil |
|---|---:|---:|---:|
| 0 | 98,10% | 83,40% | 40,30% |
| 1 | 97,25% | 79,60% | 33,25% |

Estos resultados están documentados en la documentación de `ncm-mlx`. No demuestran que el entrenamiento original sea irreproducible, porque los modelos y presupuestos no son idénticos. Sí muestran que reproducir los checkpoints oficiales y reproducir su proceso de entrenamiento son problemas diferentes. El propio proyecto reconoce que «the original million-step E19 recipe remains unstarted» («la receta original de un millón de pasos sigue sin iniciarse»).

### Tres líneas de investigación relacionadas

El desarrollo de modelos que predicen unidades superiores al token ha producido diferentes enfoques.

| Arquitectura | Objetivo principal | Característica |
|---|---|---|
| NCM | Inferencia paralela | Generación jerárquica discreta |
| NCP / ConceptLM | Eficiencia de entrenamiento | Predicción de conceptos y tokens |
| NCP-ArchPreview | Escalabilidad de NCP | Modelo de aproximadamente 8,94B |
| Cola2 | Compresión semántica | Latentes continuos y decoder de difusión |

No son variantes equivalentes. NCM modifica directamente el procedimiento de generación. NCP conserva la generación autorregresiva y añade predicción conceptual durante el entrenamiento. Cola2 combina representación semántica continua y generación discreta mediante difusión.

NCP-ArchPreview escala la arquitectura NCP a 8,9B parámetros y la entrena con 5,73T tokens del dataset Dolma-3, siendo la mayor demostración de un modelo de lenguaje en espacio latente hasta la fecha. Alcanza el loss final de OLMo-3-7B consumiendo solo el 51,3% de los tokens de entrenamiento totales de referencia, y lo supera en 2,45 puntos en el promedio macro de downstream, incluyendo una ganancia de 5,99 puntos en GSM8K. Es importante aclarar que esta cifra mide eficiencia de convergencia en tokens, no una aceleración equivalente del entrenamiento en tiempo real.

### Principal limitación operacional

NCM reduce el número de pasos secuenciales, pero esto no garantiza menor tiempo de ejecución bajo cualquier nivel de concurrencia. Una arquitectura que necesita menos evaluaciones puede realizar más trabajo total por respuesta. Por tanto, es necesario evaluar latencia individual, throughput concurrente, coste computacional total, memoria, calidad y escalabilidad.

### Conclusión ejecutiva

NCM es una innovación arquitectónica relevante y una alternativa prometedora a los modelos de difusión de lenguaje. Sus resultados justifican continuar investigando la generación jerárquica. Sin embargo, todavía no hay evidencia suficiente para considerarlo un sustituto general de los LLM autorregresivos. Su mayor oportunidad está en los escenarios donde la reducción de dependencias secuenciales aporta una ventaja efectiva sin generar un exceso de cómputo que elimine esa ganancia.

---

# 3. Tablas técnicas en Markdown y CSV

## 3.1. Resultados originales de NCM

| Tarea | Métrica | NCM | Baseline | Resultado |
|---|---|---:|---|---|
| LM1B | Gen. PPL | 93,05 | DUO: 97,30 | Mejor calidad y 21× velocidad |
| OpenWebText | Gen. PPL | 83,12 | DUO: 77,69 | Competitivo; 10× velocidad frente al baseline principal |
| XSum | ROUGE-L | 28,0 | AURORA-LM | Calidad comparable; 31× velocidad |
| Sudoku difícil | Tableros resueltos | 86,1% | FMLM+: 81,3% | +4,8 puntos porcentuales |
| Entrenamiento LM1B | Posiciones procesadas | 13,36B | 66B | 4,9× menos |

**Advertencia:** Gen. PPL es una métrica de evaluación de generaciones y no debe confundirse con el perplexity convencional calculado directamente sobre el conjunto de validación.

CSV:

```csv
Tarea,Métrica,NCM,Baseline,Resultado
LM1B,Gen PPL,93.05,DUO 97.30,21x velocidad
OpenWebText,Gen PPL,83.12,DUO 77.69,10x velocidad
XSum,ROUGE-L,28.0,AURORA-LM,31x velocidad
Sudoku dificil,Resueltos 86.1%,FMLM+ 81.3%,,4.8 puntos
Entrenamiento LM1B,Posiciones 13.36B,66B baseline,,4.9x menos
```

## 3.2. Comparación de arquitecturas posteriores

| Característica | NCM | NCP / ConceptLM | NCP-ArchPreview | Cola2 |
|---|---|---|---|---|
| Representación | Códigos discretos jerárquicos | Conceptos discretos | Conceptos discretos cuantizados | Latentes continuos |
| Predicción conceptual | Sí | Sí | Sí | Sí, en espacio continuo |
| Generación final | Paralela por niveles | Autoregresiva | Autoregresiva | Difusión por bloques |
| Cambia el paradigma de inferencia | Sí | No | No | Sí |
| Objetivo principal | Velocidad de generación | Calidad y eficiencia de entrenamiento | Escalabilidad de NCP | Compresión y generación jerárquica |
| Escala relevante | 725M | 1,5B desde cero; experimentos adicionales con Llama 8B | 8,94B (5,73T tokens) | 346.030M tokens |
| Principal evidencia | Benchmarks de velocidad | Mejoras en 13 benchmarks | Convergencia y evaluación a escala | Cinco tareas y ocho benchmarks finales |

CSV:

```csv
Dimension,NCM,NCP ConceptLM,NCP ArchPreview,Cola2
Representacion,Discreta jerarquica,Conceptos discretos,Conceptos cuantizados,Latentes continuos
Generacion,Paralela por niveles,Autoregresiva,Autoregresiva,Difusion por bloques
Objetivo,Velocidad,Entrenamiento,Escalabilidad,Compresion
Escala,725M,1.5B y Llama 8B,8.94B,346.03B tokens
```

## 3.3. Comparación independiente NCM-MLX frente a AR en TinyWorld

El proyecto independiente publica resultados de generación sintética con modelos pequeños.

| Métrica | NCM 5,0M | AR 4,8M |
|---|---:|---:|
| Frases válidas, T=1 | 89,8% | 98,6% |
| Frases válidas y no vistas | 16,3% | 23,5% |
| Llamadas de modelo | 6 + 1 decodificación | 32 |
| Latencia p50, batch 1 | 4,5 ms | 19,8–30,5 ms |
| Latencia p50, batch 256 | 37,8 ms | 49,8 ms |

Estos datos deben interpretarse exclusivamente como resultados de un benchmark sintético y de modelos pequeños. No demuestran que NCM produzca mejor texto general. La diferencia entre validez y generalización también es importante: un modelo puede producir frases gramaticalmente válidas y, aun así, tener menor capacidad para generar combinaciones nuevas.

## 3.4. Tabla consolidada de errores metodológicos

| # | Problema | Corrección |
|---|---|---|
| 1 | Comparación incompleta frente a AR | Evaluación de serving equivalente |
| 2 | KV-cache mal calculado | Incorporar cabezas KV reales |
| 3 | NCM considerado compute-bound | Modelo Roofline por nivel |
| 4 | TFLOPS máximos | Rendimiento efectivo |
| 5 | Prefill omitido | Latencia total |
| 6 | Tráfico HBM no medido | Nsight Compute |
| 7 | Agregación de tiempos | Trazas y tiempos propios |
| 8 | Sudoku sin control de orden | Diseño factorial |
| 9 | Caché entre niveles no demostrada | Verificación de kernels |
| 10 | Extrapolación a modelos grandes | Experimentos de escalabilidad |

---

# 4. Revisión matemática: Roofline, KV-cache y punto de cruce

## 4.1. Modelo de referencia: H100 y Llama 3 8B

Se utilizarán los siguientes parámetros:

| Parámetro | Valor |
|---|---:|
| GPU | NVIDIA H100 SXM |
| Modelo | Llama 3 8B |
| Parámetros | 8.000 millones |
| Precisión | BF16 |
| Pesos aproximados | 16 GB |
| Ancho de banda HBM | 3,35 TB/s |
| Rendimiento BF16 denso máximo | 989 TFLOPS |
| Capacidad HBM | 80 GB |
| Capas | 32 |
| Cabezas KV | 8 |
| Dimensión de cabeza | 128 |
| Prompt | 512 tokens |
| Generación | 128 tokens |

## 4.2. Límite inferior de lectura de pesos en AR

Para una solicitud individual, suponiendo que los pesos BF16 deben leerse desde HBM en cada paso de decodificación:

\[
T_{\min}^{\mathrm{step}}
=
\frac{P\cdot b}{BW}
=
\frac{16\cdot10^9}{3,35\cdot10^{12}}
\approx4,78\ \text{ms}
\]

Para 128 tokens:

\[
T_{\min}^{\mathrm{decode}}
=
128\cdot4,78
\approx611,8\ \text{ms}
\]

Es un límite inferior idealizado para ese escenario. No representa la latencia completa ni permite declarar imposible cualquier benchmark inferior sin comprobar primero la precisión utilizada, la cuantización, el número de parámetros reales, el número de GPU, el tamaño de batch, qué intervalos temporales se midieron y la reutilización de datos en caché. Tampoco puede extrapolarse directamente a batches grandes, porque los pesos se reutilizan entre distintas solicitudes.

## 4.3. Memoria del KV-cache

Para Llama 3 8B:

\[
M_{\mathrm{KV}}=
B\cdot2\cdot32\cdot8\cdot128
\cdot(S+t)\cdot2
\]

Para batch 64: \(M_{\mathrm{KV}}\approx9,13\ \text{GB}\). Para batch 128: \(M_{\mathrm{KV}}\approx18,25\ \text{GB}\).

La cifra depende de la longitud de contexto y de la precisión del KV-cache. No debe confundirse con el tráfico total de memoria, que depende de las lecturas efectivas durante la ejecución.

## 4.4. Atención de decodificación y régimen de memoria

La atención de decodificación accede a las claves y valores almacenados para los tokens anteriores. Su coste de lectura crece con la longitud del contexto. Sin embargo, el comportamiento completo del transformer también incorpora las proyecciones y las capas feed-forward. La intensidad aritmética total depende del batch y de la reutilización de pesos.

Por eso, no es correcto afirmar que el modelo completo permanece necesariamente memory-bound para cualquier batch. Lo correcto es distinguir atención sobre KV-cache, lectura de pesos, operaciones matriciales, reutilización de datos y throughput del sistema. La atención puede estar limitada por memoria mientras las operaciones matriciales del modelo se acercan al régimen limitado por cómputo.

## 4.5. ¿Cuál es el verdadero punto de cruce \(B^*\)?

El punto de cruce se define como el batch a partir del cual una arquitectura deja de ofrecer ventaja frente a otra bajo una métrica determinada. Sin embargo, hay varias definiciones posibles:

**Cruce de latencia:** \(T_{\mathrm{NCM}}(B^*)=T_{\mathrm{AR}}(B^*)\)

**Cruce de throughput:** \(Q_{\mathrm{NCM}}(B^*)=Q_{\mathrm{AR}}(B^*)\)

**Cruce de eficiencia:** \(\frac{Q_{\mathrm{NCM}}}{W_{\mathrm{NCM}}} = \frac{Q_{\mathrm{AR}}}{W_{\mathrm{AR}}}\)

Donde \(W\) puede representar consumo energético o coste computacional. Estos tres puntos de cruce no tienen por qué coincidir.

### Por qué no es válido afirmar que \(B^*=3,5\)

Para obtener un valor numérico reproducible se necesitan FLOPs efectivos por arquitectura, tráfico HBM medido, KV-cache real, prefill, costes de lanzamiento, longitudes de cada nivel NCM, rendimiento efectivo por batch, definición de throughput e igualdad de calidad de salida.

Sin esos datos, afirmar que el resultado corregido es 3,5 sería sustituir una estimación insuficientemente fundamentada por otra. La cifra de batch 64 publicada por MindStudio también debe interpretarse como un resultado particular de su configuración, no como una constante arquitectónica.

**Conclusión:** el punto de cruce de NCM frente a AR sigue siendo una cuestión experimental abierta.

## 4.6. Inconsistencia de escalado de los datos de emulación

La tabla original presenta NCM a batch 1 con 154,2 ms y NCM a batch 64 con 920,4 ms. La relación es \(920,4/154,2\approx5,97\), es decir, aproximadamente 6 veces más tiempo para 64 veces más solicitudes.

Esto no demuestra por sí solo que los resultados sean incorrectos. Puede existir reutilización de pesos, saturación progresiva de recursos y procesamiento matricial más eficiente a mayor batch. Sin embargo, si la tabla se presenta como resultado de un modelo simplificado de coste lineal y compute-bound, es necesario explicar cómo se obtuvieron esos valores. La documentación debería incluir las ecuaciones completas y los parámetros de utilización empleados.

---

# 5. Preguntas técnicas para los autores

Las siguientes preguntas pueden utilizarse para una réplica técnica, una discusión académica o una solicitud de aclaraciones.

## 5.1. Diseño experimental

**1. Comparación con AR.** Los resultados principales de velocidad se presentan frente a modelos de difusión. ¿Existe una evaluación completa frente a transformers autorregresivos de tamaño equivalente, utilizando idénticos niveles de calidad, batch, contexto y hardware?

**2. Serving concurrente.** ¿Han evaluado NCM con un motor de serving equivalente a vLLM? ¿Podrían publicar latencia p50, p95 y p99 y throughput para batches entre 1 y 128?

**3. Eficiencia energética.** ¿Se ha medido el consumo energético por secuencia generada? Una reducción de pasos de inferencia no garantiza necesariamente una reducción equivalente de energía.

## 5.2. Sudoku y razonamiento

**4. Orden de decodificación.** ¿Qué parte de la ventaja en Sudoku procede de la arquitectura y qué parte del orden coarse-to-fine? ¿Se han realizado ablaciones controlando el orden de llenado en los modelos de difusión?

**5. Reproducibilidad.** ¿Se han repetido los experimentos con múltiples semillas, manteniendo constantes el tamaño del modelo y el presupuesto de entrenamiento?

**6. Generalización.** ¿Se mantiene la ventaja de NCM en problemas de razonamiento que no tienen una estructura espacial tan regular como Sudoku?

## 5.3. Rendimiento computacional

**7. KV-cache.** ¿Han incorporado el tráfico real del KV-cache a sus estimaciones de throughput autorregresivo?

**8. Perfilado HBM.** ¿Podrían publicar trazas de Nsight Compute con bytes DRAM leídos y escritos, intensidad aritmética y utilización efectiva de Tensor Cores?

**9. Punto de cruce.** ¿Cuál es el batch de cruce entre NCM y AR cuando se comparan throughput, latencia y consumo energético por separado? ¿Podrían publicar el modelo analítico completo y sus parámetros?

## 5.4. Arquitectura

**10. Jerarquía adaptativa.** ¿Han considerado que el número de niveles dependa de la longitud y complejidad del texto? Una jerarquía fija podría introducir trabajo innecesario en respuestas cortas.

**11. Entrenamiento conjunto.** ¿Han evaluado entrenar conjuntamente el tokenizador y el generador? El propio trabajo identifica esta posibilidad como una dirección de investigación.

**12. Generación incremental.** ¿Es posible producir resultados parcialmente legibles antes de finalizar todos los niveles? ¿Qué compromisos de calidad y consistencia implicaría implementar streaming?

## 5.5. Escalabilidad y ecosistema

**13. Escalado.** ¿Tienen previsto evaluar NCM a 1B, 8B y más parámetros?

**14. Combinación con NCP.** ¿Han explorado integrar el objetivo de predicción conceptual de NCP en el entrenamiento de NCM?

**15. Integración con Cola2.** ¿Sería posible combinar la jerarquía discreta de NCM con una representación semántica continua y un decoder de difusión?

Estas preguntas permitirían pasar de una comparación de resultados publicados a una evaluación de las ventajas y limitaciones reales de cada paradigma.

---

# 6. Artículo divulgativo

# El modelo que quiso dejar de escribir palabra por palabra: qué ha conseguido realmente NCM

**Stanford y sus colaboradores proponen generar texto mediante representaciones jerárquicas, en lugar de producir un token después de otro. Los resultados iniciales son llamativos, pero todavía hay preguntas importantes sobre su rendimiento real, su escalabilidad y su utilidad en producción.**

## El problema de generar texto token a token

Los grandes modelos de lenguaje actuales utilizan principalmente generación autorregresiva. Cuando preguntas algo a un LLM, el modelo calcula el siguiente token, lo incorpora al contexto y vuelve a ejecutar el proceso. Este mecanismo se repite hasta completar la respuesta.

El problema es que existe una dependencia secuencial: para producir el siguiente token es necesario conocer los anteriores. Aunque las GPU modernas tienen una enorme capacidad de cálculo, generar texto también exige mover grandes cantidades de datos entre memoria y procesadores. En particular, la lectura de los pesos del modelo durante la generación puede convertirse en uno de los principales cuellos de botella.

Por eso, desde hace tiempo, los investigadores buscan maneras de reducir la cantidad de pasos secuenciales. Una de las alternativas más conocidas es la difusión de lenguaje, que permite generar varios tokens en paralelo mediante procesos iterativos de refinamiento. Pero esta estrategia también tiene dificultades: necesita múltiples evaluaciones y puede perder calidad cuando se reduce demasiado el número de pasos.

## La propuesta de NCM: primero la idea, después las palabras

En octubre de 2026, investigadores de Hazy Research de Stanford y colaboradores de Together AI presentaron Next-Concept Modeling.

Su propuesta cambia la unidad de generación. En lugar de predecir directamente cada token, primero representa el texto mediante diferentes niveles de códigos discretos. Un tokenizador multiscala basado en residual VQ-VAE construye una representación jerárquica. Después, un transformer genera esos niveles de forma progresiva. Primero aparece una representación general. Posteriormente se añaden detalles hasta obtener el texto completo.

La principal característica es que los códigos de cada nivel se predicen en paralelo. Esto reduce la dependencia secuencial y permite completar una respuesta en muchas menos evaluaciones que un generador autorregresivo convencional.

La idea es sencilla, pero sus implicaciones son importantes: quizá no sea necesario generar cada palabra de manera independiente para producir lenguaje de calidad.

## Los resultados que llamaron la atención

El artículo presenta resultados destacados:

- 21 veces más velocidad que DUO en LM1B.
- 10 veces más velocidad frente a modelos de difusión en OpenWebText.
- 31 veces más velocidad frente a AURORA-LM en XSum.
- Aproximadamente 4,9 veces menos posiciones de entrenamiento en LM1B.
- 86,1% de resolución en Sudoku difícil.

No son resultados menores. Especialmente interesante es que NCM consigue generar representaciones completas y refinarlas progresivamente. Esto abre una alternativa a la idea tradicional de que el lenguaje necesariamente debe producirse de izquierda a derecha.

Pero hay que interpretar correctamente las comparaciones. Los speedups principales se obtuvieron frente a modelos de difusión bajo protocolos específicos. No demuestran que NCM sea 10–31 veces más rápido que los LLM autorregresivos utilizados habitualmente.

## ¿Es realmente más rápido que un LLM convencional?

Esta es probablemente la pregunta más importante. NCM necesita menos evaluaciones secuenciales, pero cada evaluación puede realizar más trabajo. Por tanto, reducir el número de pasos no garantiza reducir proporcionalmente el coste computacional.

Una evaluación independiente publicada por MindStudio en octubre de 2026 encontró que NCM podía ser aproximadamente cuatro veces más rápido que un modelo autorregresivo comparable en determinadas solicitudes individuales. Sin embargo, al procesar 64 solicitudes simultáneamente, el resultado se invertía y el modelo autorregresivo conseguía mayor rendimiento.

Esto sugiere que existen dos situaciones diferentes:

**Uso individual.** La reducción de pasos secuenciales puede ofrecer una ventaja importante de latencia.

**Servicio concurrente.** El mayor trabajo computacional por respuesta puede eliminar esa ventaja cuando la GPU procesa muchas solicitudes simultáneamente.

No obstante, todavía falta una evaluación independiente suficientemente amplia para determinar dónde se encuentra el punto de cruce en diferentes modelos y GPU.

## El curioso resultado de Sudoku

Otro resultado destacado es Sudoku. NCM consigue resolver el 86,1% de los tableros difíciles, frente al 1% de un baseline autorregresivo convencional.

La explicación arquitectónica es interesante. Un modelo autorregresivo produce las celdas secuencialmente. Si comete un error al principio, puede arrastrarlo durante el resto de la generación. NCM, en cambio, construye una representación global y la refina progresivamente. Esto permite corregir decisiones anteriores.

Sin embargo, hay una cuestión metodológica importante. La estrategia de llenado también puede influir considerablemente en los resultados. Si un modelo completa primero las celdas sobre las que tiene mayor confianza, puede mejorar sustancialmente. La literatura sobre decodificación en modelos de difusión de lenguaje ha mostrado que el orden de decodificación puede transformar el rendimiento en tareas de razonamiento: PONDER (arXiv:2610.23531) reporta que un orden aprendido eleva la precisión en Sudoku visual difícil de 3,9% a 56,6%, frente a 38,7% con orden greedy basado en incertidumbre.

Por tanto, todavía es necesario separar la ventaja del procedimiento de decodificación de la ventaja arquitectónica.

## Tres caminos para ir más allá de los tokens

NCM no es la única investigación que intenta superar las limitaciones de la predicción tradicional. Existen otras dos líneas especialmente interesantes.

**1. NCM: generación jerárquica discreta.** Busca acelerar la inferencia mediante niveles de códigos que se generan en paralelo. Su objetivo principal es reducir los pasos secuenciales.

**2. NCP / ConceptLM: predicción de conceptos.** Añade un objetivo de predicción de conceptos al entrenamiento autorregresivo. En lugar de sustituir completamente la predicción de tokens, utiliza una representación conceptual que guía la generación posterior. Una línea posterior, NCP-ArchPreview, ha presentado un modelo de aproximadamente 8,94B parámetros entrenado con 5,73T tokens. Sus autores reportan que alcanza el loss final de referencia de OLMo-3-7B utilizando el 51,3% de los tokens de entrenamiento de referencia. Es importante aclarar que esta cifra mide eficiencia de convergencia en tokens, no una aceleración equivalente del entrenamiento en tiempo real.

**3. Cola2: semántica continua y generación discreta.** Cola2 utiliza representaciones latentes continuas y un decoder de difusión por bloques. Su objetivo es comprimir información semántica y permitir que la representación y el generador se adapten conjuntamente. Un checkpoint entrenado con 346.030 millones de tokens obtiene resultados superiores a Llama 3 8B en HellaSwag y StoryCloze. Sin embargo, su media en ocho benchmarks sigue siendo inferior: 60,10 frente a 66,25. Además, sus autores reconocen que el modelo todavía está lejos de converger.

Las tres líneas representan aproximaciones diferentes a un mismo problema: cómo conseguir que los modelos aprendan y generen lenguaje de forma más eficiente.

## Las limitaciones que todavía debe superar NCM

A pesar de sus resultados, NCM presenta cuestiones pendientes.

**Escalabilidad.** La evaluación de escalado llega hasta 725 millones de parámetros. Todavía no existe evidencia equivalente que permita extrapolar sus ventajas a modelos de decenas o cientos de miles de millones de parámetros.

**Streaming.** La generación jerárquica no ofrece necesariamente la misma experiencia incremental que un LLM autorregresivo. Es necesario investigar cómo presentar resultados parciales sin comprometer la consistencia.

**Entrenamiento.** El tokenizador se entrena separadamente y permanece congelado durante el entrenamiento del generador. El entrenamiento conjunto podría mejorar la adaptación entre representación y generación.

**Concurrencia.** La ventaja en latencia individual no implica necesariamente mayor throughput cuando hay muchos usuarios simultáneos.

**Reproducibilidad.** Reproducir los checkpoints oficiales es diferente de conseguir los mismos resultados entrenando desde cero. El proyecto `ncm-mlx` documenta que la receta original de entrenamiento completo sigue sin reproducirse.

Estas cuestiones todavía necesitan evidencia experimental adicional.

## ¿Qué significa todo esto para el futuro de los LLM?

La importancia de NCM no está necesariamente en reemplazar a los transformers actuales. Su principal contribución es demostrar que existen alternativas viables a la generación token a token.

Esto podría resultar especialmente útil en generación de respuestas estructuradas, resumen de documentos, traducción, generación de contenido con planificación global, sistemas que necesitan muchas respuestas simultáneas (si consiguen optimizar su coste computacional) y aplicaciones donde sea posible aprovechar la generación paralela sin sacrificar calidad.

Sin embargo, los LLM autorregresivos mantienen ventajas importantes: ecosistema, escalabilidad, compatibilidad con herramientas y sistemas de serving maduros. La comparación debe realizarse con modelos completos y cargas de trabajo reales, no únicamente mediante el número de evaluaciones del modelo.

## Conclusión: una dirección prometedora, todavía no un sustituto de los LLM

Next-Concept Modeling representa una innovación interesante en la investigación de arquitecturas de lenguaje. Demuestra que es posible generar texto mediante una jerarquía de conceptos y refinamiento progresivo, con resultados competitivos y reducciones importantes de latencia frente a determinados modelos de difusión.

Pero todavía no ha demostrado que pueda sustituir de manera general a los transformers autorregresivos. La siguiente etapa de investigación debería centrarse en tres cuestiones:

1. Escalar la arquitectura a varios miles de millones de parámetros.
2. Compararla con modelos autorregresivos bajo condiciones reales de serving.
3. Mejorar la eficiencia conjunta de representación, entrenamiento e inferencia.

La conclusión más interesante no es que NCM haya encontrado una forma definitiva de reemplazar la generación token a token. Es que ha demostrado que **la unidad de predicción de un modelo de lenguaje puede cambiar, y que todavía existe un amplio espacio de investigación más allá del siguiente token**.

---

# Referencias bibliográficas

1. Kumbong, H. et al. (2026). *Next-Concept Modeling: Fast, Parallel Coarse-to-Fine Text Generation*. arXiv:2610.14162. Hazy Research, Stanford y Together AI. https://arxiv.org/abs/2610.14162
2. Hazy Research (2026). *Next-Concept Modeling: Official implementation and released checkpoints*. Repositorio GitHub: `HazyResearch/ncm`; checkpoints en Hugging Face: `hazyresearch/ncm-checkpoints`
3. MindStudio (29 de octubre de 2026). *NCM vs LLMs: Independent Speed Benchmark Results Explained*. Evaluación independiente sobre DGX Spark. https://www.mindstudio.ai/blog/ncm-vs-llm-speed-benchmark-test
4. janmus1c (2026). *ncm-mlx: Next-Concept Modeling in MLX*. Implementación independiente, checkpoints oficiales y experimentos de entrenamiento. https://pypi.org/project/ncm-mlx/
5. Liu, Y. et al. (2026). *Next Concept Prediction in Discrete Latent Space Leads to Stronger Language Models*. arXiv:2602.08984. LUMIA Lab, Shanghai Jiao Tong University y Shanghai AI Laboratory. https://arxiv.org/abs/2602.08984
6. NCP Team (2026). *NCP-ArchPreview Technical Report: Moving towards Latent Space Language Models through Next Concept Prediction*. arXiv:2609.10715. https://arxiv.org/abs/2609.10715
7. Guo, H. et al. (2026). *Cola2: Co-Adaptive Hierarchical Language Modeling with Continuous Semantic Compression and Balanced Discrete Generation*. arXiv:2610.31305. https://arxiv.org/abs/2610.31305
8. Williams, S., Waterman, A. y Patterson, D. (2009). *Roofline: An Insightful Visual Performance Model for Multicore Architectures*. Communications of the ACM, 52(4).
9. NVIDIA (2024–2026). *H100 Tensor Core GPU Datasheet*. Especificaciones de memoria, ancho de banda y rendimiento computacional: BF16 denso 989 TFLOPS, BF16 con sparsity 1.979 TFLOPS, HBM 3,35 TB/s. TF32 denso 494 TFLOPS; con sparsity 989 TFLOPS.
10. NVIDIA (2026). *Nsight Compute Profiling Guide*. Métricas de tráfico DRAM, rendimiento y análisis de kernels.
11. PyTorch (2026). *torch.profiler documentation*. Instrumentación y análisis de ejecución.
12. PONDER (2026). *PONDER: Learning to Generate in the Right Order*. arXiv:2610.23531. Resultado de orden aprendido en Sudoku visual: 3,9% → 56,6%; orden greedy por incertidumbre: 38,7%. https://arxiv.org/abs/2610.23531

---

# Evaluación final del informe

| Dimensión | Evaluación |
|---|---|
| Rigor técnico | Alto |
| Fundamentación matemática | Corregida y delimitada |
| Contraste bibliográfico | Alto |
| Separación entre evidencia e hipótesis | Explícita |
| Reproducibilidad | Analizada |
| Comparación arquitectónica | Ampliada |
| Utilidad para investigación | Alta |
| Aplicabilidad a producción | Condicionada a nuevos benchmarks |

**Dictamen final:** NCM merece considerarse una línea de investigación seria en generación de lenguaje. Sus resultados iniciales son suficientemente sólidos para justificar nuevas investigaciones, pero no para afirmar superioridad general frente a los LLM autorregresivos. La prioridad debe ser demostrar su eficiencia end-to-end, su escalabilidad y su rendimiento bajo cargas reales de producción.

## Fuentes principales contrastadas

- **NCM original:** [Artículo científico de NCM (arXiv:2610.14162)](https://arxiv.org/abs/2610.14162)
- **Implementación oficial:** [HazyResearch/NCM en GitHub](https://github.com/HazyResearch/ncm); [checkpoints en Hugging Face](https://huggingface.co/hazyresearch/ncm-checkpoints)
- **Replicación independiente:** [ncm-mlx en PyPI](https://pypi.org/project/ncm-mlx/)
- **Benchmark independiente DGX Spark:** [MindStudio — NCM vs LLMs](https://www.mindstudio.ai/blog/ncm-vs-llm-speed-benchmark-test)
- **NCP / ConceptLM:** [Artículo científico de NCP (arXiv:2602.08984)](https://arxiv.org/abs/2602.08984)
- **NCP-ArchPreview 8.9B:** [Informe técnico (arXiv:2609.10715)](https://arxiv.org/abs/2609.10715)
- **Cola2:** [Artículo científico de Cola2 (arXiv:2610.31305)](https://arxiv.org/abs/2610.31305)
- **PONDER / orden de decodificación:** [arXiv:2610.23531](https://arxiv.org/abs/2610.23531)
- **NVIDIA H100:** [Especificaciones oficiales](https://resources.nvidia.com/en-us-gpu/h100-datasheet-24306)
- **Nsight Compute:** [Documentación de perfilado NVIDIA](https://docs.nvidia.com/nsight-compute/ProfilingGuide/)

### Mi valoración

La mejora más importante respecto al documento inicial es que ahora no se intenta demostrar que NCM pierde frente a AR mediante un cálculo incompleto. Se establece qué está demostrado, qué está cuestionado y qué experimentos faltan.

Eso hace que el informe sea mucho más defendible técnicamente y adecuado para una discusión con investigadores.

El siguiente paso que más valor aportaría sería desarrollar un **benchmark reproducible NCM vs. AR vs. NCP vs. Cola2**, con métricas de calidad, FLOPs, HBM, latencia, throughput y consumo energético.

---

## Nota editorial de verificación (2026-11-08)

Esta v2 se incorpora como **referencia principal del proyecto**. No todas sus
cifras tienen el mismo nivel de evidencia; esta nota separa lo verificado, lo
corregido y lo que sigue siendo una propuesta no ejecutada.

### Correcciones aplicadas al texto

| # | Ubicación | Problema | Corrección aplicada |
|---|---|---|---|
| 1 | §1.3, tabla H100 | «TF32 Tensor Core: 989 TFLOPS» sin distinguir denso/sparse | TF32 denso = **494 TFLOPS**; TF32 con sparsity = **989 TFLOPS**. BF16 denso = 989; BF16 sparse = 1.979. |
| 2 | §1.7 y §6, Sudoku 3,9%→56,6% | Atribuía el 56,6% a un orden «basado en incertidumbre» | PONDER: **orden aprendido** = 56,6%; **orden greedy por incertidumbre (SRM)** = 38,7%; orden aleatorio = 3,9%. Se añadió PONDER a referencias. |
| 3 | §4.4 | «El paper original nunca comparó contra un AR estándar» | El paper **sí** incluye un baseline AR en Sudoku (1,0% difícil). Lo que no presenta es una comparación sistemática de **serving** contra AR. Redacción corregida. |
| 4 | §2.2 | Los porcentajes scratch podían leerse como replicación limpia del paper | Son un modelo más pequeño y una receta distinta; `ncm-mlx` lo documenta como resultados de entrenamiento propio, no como reproducción exacta del checkpoint oficial. |
| 5 | §2.2 | Cita traducida de la receta de un millón de pasos | Se conserva la cita original en inglés: «The original million-step E19 recipe remains unstarted». |

### Verificación de cifras y fuentes

| Bloque | Estado | Evidencia / nota |
|---|---|---|
| NCM 21×/10×/31× vs DLMs; 4–5× menos tokens; Sudoku 86,1%; 725M | **Verificado** | arXiv:2610.14162, abstract, §4.3–§4.6, Tabla 3, Apéndice I. |
| El paper compara AR en Sudoku, pero no hace benchmark de serving AR | **Verificado con matiz** | Tabla 3: AR 14,6/5,1/1,0%; los speedups principales son frente a DLMs. No hay evaluación de serving con vLLM ni batch 1–128. |
| KV-cache Llama-3-8B, B=64, S=512, t=576, BF16 | **Verificado** | Fórmula GQA: \(B\cdot2\cdot32\cdot8\cdot128\cdot1088\cdot2\) = **9,13 GB**; B=128 = **18,25 GB**. La v1 usaba 19,3/38,6 GB y queda sustituida. |
| Prefill 8B, S=512 | **Verificado aritméticamente** | \(2PS=8,192\) TFLOPs; a 989 TFLOPS = **8,3 ms** como cota inferior. No es una latencia medida. La cifra de 133 µs de la v1 queda descartada. |
| \(B^*=3,5\) | **Rechazado como constante** | Depende de TFLOPS efectivos, KV-cache, prefill, schedule y definición de cruce. El punto de cruce sigue abierto; no citar 3,5 como resultado. |
| H100 BF16 denso 989 / sparse 1.979; HBM 3,35 TB/s; ridge ~295 | **Verificado** | Especificaciones NVIDIA H100 SXM y cálculo 989/3,35. |
| H100 TF32 denso 494 / sparse 989 | **Corregido** | El texto original ponía 989 sin aclarar sparsity. |
| `ncm-mlx` Sudoku 99,40/96,30/86,20 | **Verificado** | `docs/EXPERIMENTS.md`: 1.988/2.000, 1.926/2.000, 1.724/2.000; paper 99,5/96,5/86,1. |
| `ncm-mlx` scratch 98,10/83,40/40,30 y 97,25/79,60/33,25 | **Verificado** | `docs/EXPERIMENTS.md`, E19-funded y E20; modelo más pequeño y receta distinta. |
| «The original million-step E19 recipe remains unstarted» | **Verificado** | `docs/EXPERIMENTS.md`, E19-funded. |
| `ncm-mlx-tinyworld` 5,0M/1,3M/4,8M y tabla de latencia | **Verificado** | Model card `janmusic/ncm-mlx-tinyworld` y `docs/EXPERIMENTS.md`: p50 4,5/5,8/37,8 ms NCM; 30,5/22,9/49,8 ms AR. |
| PONDER 3,9%→56,6% (orden aprendido) y 38,7% (SRM) | **Verificado en el preprint** | arXiv:2610.23531, Tabla 1; no replicado localmente ni revisado por pares en esta verificación. |
| MindStudio ~4× single, ~2× resumen, AR gana a batch 64 | **Secundario** | Blog independiente, 29 Oct 2026; no es revisión por pares. No universal. |
| NCP-ArchPreview 8,9B, 5,73T, 51,3%, +2,45 macro, +5,99 GSM8K | **Verificado** | arXiv:2609.10715. |
| Cola2 346,03B tokens; 60,10 vs 66,25 de media; gana solo HellaSwag/StoryCloze | **Verificado** | Model card ByteDance-Seed/Cola2; 41,75 vs 39,21 y 80,42 vs 79,49. |
| NCM sin streaming real, longitud fija y tokenizer/generador por tarea | **Verificado** | Paper, Apéndice I; servidor local buffered. |
| NCM listo para producción | **No** | El propio informe concluye lo contrario; no hay benchmark de serving completo. |

### Estado operativo local observado (2026-11-08)

- `ncm-lm1b.service`: **active/enabled**, loopback `127.0.0.1:11436`.
- `GET /health`: `status=ok`, `params=724.800.640`, `vram_mb=3410,4`,
  `load_s=13,765`, `unconditional=true`, `prompt_ignored=true`,
  `fixed_length=128`.
- Gateway `free-ai-gateway`: **active**, con proveedor `ncm-lm1b` visible.
- `ncm-lm1b/ncm-lm1b-large` es un generador **unconditional**: ignora el prompt
  y no debe entrar en `auto` ni usarse como chat.
- Benchmark local previo (`ncm_bench.py`, RTX 3070 Laptop 8 GB, n=8, bs=8,
  128 tokens): **522,9 tok/s**, 3.838 MB de VRAM pico. Es una medición local de
  generación unconditional, **no** una comparación NCM vs AR y **no** un
  resultado de H100.
- `ollama.service` y `ncm-instruct.service`: **inactivos**. No se iniciaron,
  detuvieron ni modificaron servicios para esta revisión.

### Límites de esta referencia

1. **No se ejecutó el benchmark H100** de la §4 ni la matriz de serving de la
   §5. Las tablas de latencia/throughput son, como mucho, cotas o hipótesis.
2. **No hay comparación pareada NCM vs AR** en este equipo: el NCM local es
   LM1B-large 725M unconditional y el AR disponible es Qwen3.5-9B Q4_K_M
   (inactivo); no tienen el mismo tamaño, tokenizer, tarea ni presupuesto.
3. **No hay checkpoints NCP-ArchPreview ni Cola2** instalados localmente; no se
   midieron.
4. **No hay medición de energía** (NVML) ni trazas Nsight Compute.
5. El benchmark propuesto al final del informe sigue siendo un **trabajo
   pendiente**, no un resultado.

### Qué haría falta para el benchmark reproducible propuesto

- Un AR de tamaño comparable al NCM evaluado, con el mismo tokenizer, tarea,
  precisión y presupuesto de salida.
- Checkpoints oficiales de NCM para LM1B, XSum y Sudoku; el equipo solo tiene
  LM1B-large instalado.
- Un motor de serving AR (vLLM o equivalente) y un harness NCM con batching
  real, no solo llamadas HTTP secuenciales.
- Warmup, ≥5 repeticiones, seeds fijas, p50/p95/p99, throughput, VRAM pico,
  energía y métricas de calidad por tarea.
- Nsight Compute para bytes DRAM y utilización de Tensor Cores; el profiler de
  PyTorch por sí solo no basta.
- Declarar explícitamente single-request vs batch, y no llamar «TTFT» al primer
  nivel coarse de NCM.

### Fuentes consultadas para esta nota

- NCM: https://arxiv.org/abs/2610.14162
- `ncm-mlx` experimentos: https://github.com/janmus1c/ncm-mlx/blob/main/docs/EXPERIMENTS.md
- `ncm-mlx` TinyWorld: https://huggingface.co/janmusic/ncm-mlx-tinyworld
- MindStudio: https://www.mindstudio.ai/blog/ncm-vs-llm-speed-benchmark-test
- PONDER: https://arxiv.org/abs/2610.23531
- NCP: https://arxiv.org/abs/2602.08984
- NCP-ArchPreview: https://arxiv.org/abs/2609.10715
- Cola2: https://arxiv.org/abs/2610.31305
- H100: https://resources.nvidia.com/en-us-gpu/h100-datasheet-24306
- Nsight Compute: https://docs.nvidia.com/nsight-compute/ProfilingGuide/
