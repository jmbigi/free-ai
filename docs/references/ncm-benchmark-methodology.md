# Metodología de benchmark NCM vs AR/vLLM (referencia aportada)

> Documento de referencia aportado por el programador el 2026-11-08. Es una
> **propuesta metodológica**, no un conjunto de resultados medidos. Las
> correcciones y advertencias de la sección final son obligatorias para no
> presentar pseudocódigo o expectativas como evidencia (regla 14).
>
> Referencia principal vigente: [ncm-primary-reference-v2.md](ncm-primary-reference-v2.md).
> El benchmark NCM vs AR/NCP/Cola2 propuesto **no se ejecutó**; no hay
> resultados medidos en este repositorio.

---

# Arquitectura del Benchmark: NCM vs. AR (vLLM)

```
                       ┌─────────────────────────────────────────────────┐
                       │           ORQUESTADOR DEL BENCHMARK             │
                       │ (Generador de Carga, Metrics Collector, Tracing)│
                       └───────────────────────┬─────────────────────────┘
                                               │
                       ┌───────────────────────┴─────────────────────────┐
                       ▼                                                 ▼
        ┌───────────────────────────────┐               ┌───────────────────────────────┐
        │   ENGINE A: NCM CUSTOM ENGINE │               │    ENGINE B: vLLM ENGINE      │
        │ ┌───────────────────────────┐ │               │ ┌───────────────────────────┐ │
        │ │   RVQ Hierarchical Decoder│ │               │ │ PagedAttention KV-Cache   │ │
        │ └─────────────┬─────────────┘ │               │ └─────────────┬─────────────┘ │
        │ ┌─────────────▼─────────────┐ │               │ ┌─────────────▼─────────────┐ │
        │ │ Parallel Level Predictor  │ │               │ │ Autoregressive Token Engine│ │
        │ └───────────────────────────┘ │               │ └───────────────────────────┘ │
        └───────────────┬───────────────┘               └───────────────┬───────────────┘
                        │                                               │
                        └───────────────────────┬───────────────────────┘
                                                ▼
                               ┌─────────────────────────────────┐
                               │     PROFILING & METRICS LAYER   │
                               │  (PyTorch Profiler, NVTX, GPU)  │
                               └─────────────────────────────────┘
```

---

## 1. Métrica 1: Profiling Teórico y Empírico de FLOPs

Para evitar distorsiones por optimizaciones de software, el benchmark mide FLOPs en dos niveles: un modelo analítico exacto y trazado de kernels GPU mediante NVTX + PyTorch Profiler.

### 1.1 Modelo Matemático de Contabilidad de FLOPs

#### A. Transformer Autorregresivo (AR con KV-Cache)

Para una secuencia con un prompt de longitud $S$ y una respuesta generada de longitud $L$, usando un modelo con $N_{\text{layer}}$ capas, dimensión de modelo $d_{\text{model}}$ y extensión FFN $d_{\text{ffn}} \approx 4 d_{\text{model}}$:

* **Fase Prefill (Prompt $S$):**

$$\text{FLOPs}_{\text{prefill}} \approx 2 S \cdot \left( 12 N_{\text{layer}} d_{\text{model}}^2 + 2 N_{\text{layer}} d_{\text{model}} d_{\text{ffn}} \right) + 2 N_{\text{layer}} S^2 d_{\text{model}}$$

* **Fase Decode (por cada token $t \in [1, L]$ usando KV-Cache):**

$$\text{FLOPs}_{\text{decode}}(t) \approx 2 \cdot \left( 12 N_{\text{layer}} d_{\text{model}}^2 + 2 N_{\text{layer}} d_{\text{model}} d_{\text{ffn}} \right) + 4 N_{\text{layer}} (S + t) d_{\text{model}}$$

* **Total AR FLOPs:**

$$\text{FLOPs}_{\text{AR\_Total}} \approx \text{FLOPs}_{\text{prefill}} + \sum_{t=1}^{L} \text{FLOPs}_{\text{decode}}(t)$$

#### B. Next-Concept Modeling (NCM)

NCM opera sobre $K$ niveles jerárquicos ($k=1 \dots K$), donde cada nivel procesa una representación de longitud $\ell_k$ (con $\ell_1 < \ell_2 < \dots < \ell_K = L$). Al predecir el nivel $k$, el Transformer computa sobre la longitud $\ell_k$ completa.

* **Costo por Nivel Jerárquico $k$:**

$$\text{FLOPs}_{\text{NCM}}(k) \approx 2 \ell_k \cdot \left( 12 N_{\text{layer}} d_{\text{model}}^2 + 2 N_{\text{layer}} d_{\text{model}} d_{\text{ffn}} \right) + 2 N_{\text{layer}} \ell_k^2 d_{\text{model}}$$

* **Costo del Decodificador VQ-VAE (Residual Vector Quantizer):**

$$\text{FLOPs}_{\text{VQ}} \approx \sum_{k=1}^{K} \text{Decoder}_{\text{CNN/Transformer}}(\ell_k)$$

* **Total NCM FLOPs:**

$$\text{FLOPs}_{\text{NCM\_Total}} = \sum_{k=1}^{K} \text{FLOPs}_{\text{NCM}}(k) + \text{FLOPs}_{\text{VQ}}$$

> **Impacto analítico:** Aunque $K \ll L$ (ej. $K=11$ pasos vs. $L=128$ tokens), la suma de longitudes pasadas por el Transformer $\sum_{k=1}^K \ell_k$ suele superar a $L$. En un escenario $L=128$, $\sum \ell_k$ puede alcanzar $\sim 639$ posiciones pasadas por atención, haciendo que los FLOPs totales de NCM sean mayores que los del modelo AR.

### 1.2 Módulo de Trazado de FLOPs GPU (PyTorch Profiler Code)

```python
import torch
from torch.profiler import profile, RecordActivity, ProfilerActivity

def profile_model_flops(model, inputs, model_type="AR"):
    """
    Captura FLOPs empíricos ejecutados en Tensor Cores utilizando NVTX y PyTorch Profiler.
    """
    with profile(
        activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA],
        with_flops=True,
        record_shapes=True,
        profile_memory=True
    ) as prof:
        with torch.no_grad():
            if model_type == "AR":
                # Generación token a token
                model.generate(**inputs, use_cache=True)
            elif model_type == "NCM":
                # Inferencia jerárquica por niveles (K forward passes)
                model.generate_hierarchical(**inputs)

    total_flops = sum([evt.flops for evt.fetchall_nodes() if evt.flops is not None])
    print(f"[{model_type}] Total FLOPs Ejecutados: {total_flops / 1e12:.4f} TFLOPs")
    return prof
```

---

## 2. Métrica 2: Latencia TTFT (Time To First Token) y TPU/GPU Latency Profile

En modelos tradicionales, TTFT mide la latencia de la fase Prefill. En NCM, la interfaz de salida es por niveles coarse-to-fine, por lo que adaptamos la definición de TTFT a **Time To First Usable Token / First Meaningful Draft (TTFT-NCM)**.

### 2.1 Definiciones Rigurosas de Latencia

* **TTFT (AR - Autorregresivo):**

$$\text{TTFT}_{\text{AR}} = t_{\text{prefill}} + t_{\text{decode\_token\_1}}$$

* **TTFT (NCM - Nivel Coarse $k=1$):**
El tiempo para entregar el esquema estructural inicial (Primer nivel conceptual).

$$\text{TTFT}_{\text{NCM\_coarse}} = t_{\text{encode\_prompt}} + t_{\text{forward\_level\_1}}$$

* **Total Time to Final Output (TFO - Respuesta Completa):**

$$\text{TFO}_{\text{AR}} = t_{\text{prefill}} + \sum_{t=1}^{L} t_{\text{step}}(t)$$

$$\text{TFO}_{\text{NCM}} = t_{\text{encode\_prompt}} + \sum_{k=1}^{K} t_{\text{forward\_level}}(k) + t_{\text{decode\_VQ}}$$

---

### 2.2 Harness de Medición de Latencia con CUDA Events

```python
import time
import torch

class LatencyProfiler:
    def __init__(self, device='cuda'):
        self.device = device
        self.start_event = torch.cuda.Event(enable_timing=True)
        self.end_ttft = torch.cuda.Event(enable_timing=True)
        self.end_tfo = torch.cuda.Event(enable_timing=True)

    def benchmark_ar(self, model, prompt_tokens, max_new_tokens):
        torch.cuda.synchronize()
        self.start_event.record()

        # Prefill + Token 1
        with torch.no_grad():
            outputs = model(prompt_tokens, use_cache=True)
            next_token = torch.argmax(outputs.logits[:, -1, :], dim=-1)
            self.end_ttft.record()

            # Resto de tokens
            past_key_values = outputs.past_key_values
            curr_token = next_token.unsqueeze(-1)
            for _ in range(max_new_tokens - 1):
                out = model(curr_token, past_key_values=past_key_values, use_cache=True)
                curr_token = torch.argmax(out.logits[:, -1, :], dim=-1).unsqueeze(-1)
                past_key_values = out.past_key_values

            self.end_tfo.record()

        torch.cuda.synchronize()
        return {
            "TTFT_ms": self.start_event.elapsed_time(self.end_ttft),
            "TFO_ms": self.start_event.elapsed_time(self.end_tfo)
        }

    def benchmark_ncm(self, ncm_model, prompt_tokens, K_levels):
        torch.cuda.synchronize()
        self.start_event.record()

        with torch.no_grad():
            # Codificación y Nivel 1 (Coarse Concept)
            context = ncm_model.encode_prompt(prompt_tokens)
            level_1_codes = ncm_model.predict_level(level=1, context=context)
            self.end_ttft.record()

            # Niveles iterativos restantes 2..K
            accumulated_codes = [level_1_codes]
            for k in range(2, K_levels + 1):
                level_k_codes = ncm_model.predict_level(level=k, context=context, prev_codes=accumulated_codes)
                accumulated_codes.append(level_k_codes)

            final_tokens = ncm_model.vq_decoder.decode(accumulated_codes)
            self.end_tfo.record()

        torch.cuda.synchronize()
        return {
            "TTFT_Coarse_ms": self.start_event.elapsed_time(self.end_ttft),
            "TFO_ms": self.start_event.elapsed_time(self.end_tfo)
        }
```

---

## 3. Métrica 3: Evaluador de Throughput Bajo Carga Concurrente (vLLM Engine Benchmark)

En un entorno real de producción (Batching Dinámico/Continuo), los modelos autorregresivos maximizan la saturación de los Tensor Cores mediante la reutilización de bloques de memoria GPU (**PagedAttention**). NCM, al procesar en paralelo todos los códigos de un nivel determinado, no utiliza la misma estructura de memoria KV-Cache.

### 3.1 Tensión Arquitectónica en Servido Concurrente

| Característica | Transformer AR (vLLM Engine) | Next-Concept Modeling (NCM Custom Engine) |
| --- | --- | --- |
| **Acceso a VRAM** | Bound por Ancho de Banda (Memory-bound en Decode) | Bound por Cómputo (Compute-bound en Compute Levels) |
| **Estructura de Memoria** | Bloques de Memoria VRAM Paginada (`PagedAttention`) | Tensores de Representación Completa en cada Nivel |
| **Comportamiento en Batch Grande ($B \ge 32$)** | La reutilización de KV-Cache mantiene alto Throughput | Múltiples pasadas sobre secuencias completas ahogan la VRAM y saturan las SMs |

### 3.2 Arquitectura del Servidor de Carga Sintética

Para comparar el Throughput (Tokens/segundo globales) bajo diferentes tamaños de *batch* ($B \in \{1, 8, 16, 32, 64, 128\}$), configuramos un arnés con tráfico estocástico (Poisson Distribution).

```python
import asyncio
import time
import numpy as np

class ThroughputBenchmarkOrchestrator:
    def __init__(self, request_rate, total_requests, prompt_len=128, gen_len=128):
        self.request_rate = request_rate
        self.total_requests = total_requests
        self.prompt_len = prompt_len
        self.gen_len = gen_len

    async def generate_poisson_load(self, engine_call_fn):
        """
        Envía peticiones simulando una distribución de llegada Poisson.
        """
        tasks = []
        start_time = time.perf_counter()

        for i in range(self.total_requests):
            # Intervalo entre peticiones basado en distribución exponencial
            interval = np.random.exponential(1.0 / self.request_rate)
            await asyncio.sleep(interval)

            # Lanzar inferencia asíncrona en el motor correspondiente
            task = asyncio.create_task(engine_call_fn(request_id=i, p_len=self.prompt_len, g_len=self.gen_len))
            tasks.append(task)

        results = await asyncio.gather(*tasks)
        total_time = time.perf_counter() - start_time

        # Cálculo de Throughput
        total_tokens = sum([r['generated_tokens'] for r in results])
        throughput = total_tokens / total_time

        print(f"Throughput Global: {throughput:.2f} tokens/sec | Tiempo Total: {total_time:.2f} s")
        return throughput
```

---

## 4. Matriz de Configuración del Experimento

Para asegurar una comparación "manzana con manzana", los dos motores deben configurarse bajo los mismos límites de presupuesto de hardware y longitud de contexto.

```
                  MATRIZ DE EVALUACIÓN EXPERIMENTAL

   Hardware Base: 1x NVIDIA H100 SXM (80GB VRAM) / CUDA 12.x
   --------------------------------------------------------
   Configuraciones de Dataset:
   ├── Low-Density: TinyStories (Generación Corta, L=128)
   └── High-Density: XSum / GSM8K (Razonamiento / Resumen, L=512)

   Variables Independientes:
   ├── Batch Size (B): [1, 4, 8, 16, 32, 64, 128]
   ├── Context Length (S): 128, 512, 1024
   └── Engine Setup:
       ├── Engine A: NCM PyTorch / MLX Custom Pipeline
       └── Engine B: vLLM (PagedAttention, Continuous Batching, FP16)
```

---

## 5. Cuadro Consolidado de Diagnóstico Esperado

A partir de la dinámica de cómputo descrita, la siguiente tabla resume los resultados esperados según el régimen de ejecución:

| Escenario de Evaluación | Ganador Esperado | Razón Arquitectónica |
| --- | --- | --- |
| **Single-Request ($B=1$), Baja Latencia** | **NCM** | $K$ pasadas paralelas ejecutan menos saltos secuenciales a memoria que $L$ iteraciones autorregresivas. |
| **Batch Concurrente Alto ($B \ge 32$)** | **AR (vLLM)** | vLLM reutiliza memoria vía *PagedAttention*. NCM satura el ancho de banda al procesar $\sum \ell_k$ posiciones por cada muestra. |
| **Prefill / TTFT Inicial** | **AR** | AR sólo ejecuta 1 forward pass sobre el prompt ($S$). NCM debe codificar y realizar la proyección del primer nivel jerárquico. |
| **Generación de Secuencia Completa (TFO)** | **NCM** (en batch chico) | NCM requiere solo $K$ forward passes (ej. $K=11$) frente a $L=128$ pasos de decodificación en AR. |

---

## Verificación y correcciones (2026-11-08)

| Afirmación / bloque | Estado | Corrección / nota |
|---|---|---|
| Hardware H100 80 GB | **Propuesta, no medición local** | Este equipo es una RTX 3070 Laptop de 8 GB; la matriz no es ejecutable tal cual. Para local usar B≤8, contexto ≤8192 y modelos que quepan. |
| Fórmulas FLOPs AR/NCM | **Aproximaciones** | Las constantes dependen de la convención (QKV+O, MLP, atención) y del prefijo; no son cotas exactas. Usar una única convención y validar con profiler/Nsight Compute. |
| `evt.fetchall_nodes()` | **Pseudocódigo inválido** | PyTorch Profiler no expone `fetchall_nodes()`; usar `prof.key_averages()`/`prof.events()` y `sort_by="flops"`, o Nsight Compute para FLOPs de hardware. |
| TTFT-NCM coarse | **No es TTFT usable** | El primer nivel coarse no es texto legible; NCM no hace streaming real. Medir TFO y, si se quiere, “time to first coarse level” como métrica separada, nunca como primer token de usuario. |
| Batch “≥32” AR gana | **Extrapolación** | El benchmark independiente midió **batch 64**; medir 1/8/16/32/64/128 en el hardware objetivo. |
| Matriz de variables | **Adecuada como guía** | Añadir warmup, repeticiones, seeds, p50/p95, errores, memoria pico y energía; no solo promedio. |
| Carga Poisson | **Pseudocódigo** | `asyncio.gather` sin límite puede agotar memoria; usar concurrencia acotada, open-loop/closed-loop declarado, y medir latencia de cola. |
| Cuadro de diagnóstico esperado | **Hipótesis** | Coincide cualitativamente con el benchmark independiente (single-request NCM; batch 64 AR), pero no es un resultado medido. |
| vLLM/PagedAttention | **Referencia verificable** | Kwon et al., SOSP 2023; el texto original dice “SIGSYS”, debe ser **SOSP**. |
| NCM paper | **Referencia verificable** | arXiv:2610.14162; límites en Apéndice I (task-specific, longitud fija, sin streaming). |

### Recomendaciones para una ejecución válida

1. **Un solo presupuesto de hardware** y modelos con parámetros comparables; declarar cuantización, tokenizer y longitud.
2. **Warmup + ≥5 repeticiones + seeds fijas**; reportar p50/p95, no solo media.
3. **TFO y throughput** como métricas principales; TTFT solo para AR y “time to first coarse level” para NCM, sin llamarlo token usable.
4. **FLOPs:** analítico + `torch.profiler` + Nsight Compute; declarar qué operaciones se cuentan.
5. **Batch:** medir 1/8/16/32/64/128; no extrapolar desde 64.
6. **Streaming:** NCM no lo tiene; cualquier SSE de NCM es buffered y debe declararse.
7. **Memoria:** VRAM pico, offload CPU/GPU y OOM; no solo tokens/s.
8. **Calidad:** no mezclar velocidad con calidad; medir por tarea (Gen. PPL, ROUGE, BLEU, exact match) y reportar el coste.
