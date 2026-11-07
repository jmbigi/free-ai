# AGENTS.md — Reglas del proyecto (Free AI Gateway)

> Registro de reglas/requerimientos indicados por el programador para este proyecto.  
> Aplican a todo cambio futuro en `/home/admin/free-ai`. Las reglas de verificación, honestidad, seguridad y no destrucción de los AGENTS globales del entorno también aplican.

## Reglas del programador (obligatorias)

1. **Investigación obligatoria en Internet antes de implementar/mejorar.** Usar y verificar recursos disponibles en Internet para elegir/ajustar integraciones, compatibilidad y buenas prácticas.
2. **Acceso agregado a todo lo gratuito disponible.** El gateway debe agregar y enrutar a las APIs/modelos gratuitos/configurables disponibles (proveedores free tier, rutas `:free`, cuentas agregadas en `.env`, y fallback cuando una fuente falla por cuota/límite/capacidad).
3. **Una sola API key para clientes del gateway.** Los clientes acceden con **1 API key** simple; esa clave se valida contra `.env` `API_KEY`. No exponer claves upstream a clientes.
4. **Servicio productivo y accesible.** Debe correr como servicio estable/accesible (no solo script manual efímero), con verificación de estado, arranque confiable y endpoints operativos.
5. **Compatibilidad máxima de API key/cliente IA.** Debe ser lo más avanzado y compatible posible con integraciones tipo OpenAI API key: KiloCode, OpenCode, DeepSeek harness y clientes compatibles. Mantener aliases de rutas/auth/body (`/v1`, `/openai/v1`, `/api/v1`, `Authorization: Bearer`, `api-key`, `x-api-key`, query/body key según seguridad operativa; `messages`/`prompt`/`input`, `max_completion_tokens`, streaming SSE).
6. **Acceso remoto con API key simple y máxima cobertura disponible.** Objetivo operativo: maximizar acceso a APIs remotas gratuitas/configurables mediante una API key simple del gateway, `model:"auto"` y fallback. **Limitación real obligatoria a declarar:** no existe inferencia remota avanzada verdaderamente ilimitada y gratis sin restricciones; los proveedores aplican cuotas, rate limits, créditos, términos o capacidad variable. Nunca afirmar “ilimitado” como garantía técnica absoluta; reportar estado real de cuentas/proveedores con evidencia.
7. **Interfaces modernas y avanzadas.** UI moderna, endpoints de salud/modelos/proveedores/cache, documentación usable (README/compatibilidad/Swagger), respuestas con metadata útil (`gateway.cache`, `gateway.context`, intentos/fallback cuando aplique).
8. **Caché de prompts y respuestas.** Implementar y mantener caché (TTL/configurable) para prompts/respuestas cacheables; controles explícitos (`cache`/`no_cache`/`temperature=0`/no stream); invalidación/expiración; endpoints de inspección/limpieza; no cachear errores ni streams completos como respuesta cacheada inválida.
9. **Compresión de contextos + prompts.** Comprimir contexto/historial antes de enrutar cuando sea necesario o se solicite (resumen de historial, preservación de instrucciones recientes/sistema, recorte por límites, metadata de compresión). Debe mejorar cabida/costo/compatibilidad sin ocultar que hubo compresión.
10. **Máximo nivel técnico (“lo más avanzado que existe”).** Realizar el mejor esfuerzo técnico: investigar, mejorar, revisar cambios, verificar con evidencia, endurecer compatibilidad/operación y mantener calidad productiva. Las afirmaciones de capacidad deben ser verificables.
11. **Proceso de entrega (cuando aplique).** Investigar en Internet; mejorar; revisar todos los cambios; commit/push cuando haya destino remoto autorizado/configurado. Seguir reglas de `jmbigi/thinker` en lo aplicable: verificación con evidencia, honestidad (sin afirmar sin salida), no secretos, no destrucción, alcance controlado, y gates/auditorías si el repo/flujo los provee. **No inventar remotos ni hacer push sin destino/permiso verificable.**

## Estado real registrado (2026-11-07, verificado localmente)
- Servicio: `free-ai-gateway.service` activo/habilitado en `0.0.0.0:8000`, `Linger=yes`.
- Cuentas `.env` detectadas: `OPENROUTER_API_KEY`, `HUGGINGFACE_API_KEY`/`HUGGING_FACE_API_KEY`. Estado observado en pruebas: OpenRouter con límite/cuota free en rutas probadas; Hugging Face router con restricción de créditos/proveedores habilitados en ruta probada; token HF válido. Pollinations disponible como fuente anónima con rate limits.
- Verificaciones: auth 401 sin key; `auto` responde con fallback; caché miss→hit; compresión de contexto activa con metadata; commit local `bc80551`. **Push pendiente**: no hay remote configurado.
