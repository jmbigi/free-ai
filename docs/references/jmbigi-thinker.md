# Referencia: jmbigi/thinker (capa de pensamiento)

- Repo: https://github.com/jmbigi/thinker
- Licencia: **GPL-3.0-only**
- Módulos relevantes: `pensamiento_layer.py` (7 pasos de investigación),
  `thinking_engine.py` (validación por pasos, ToT), `veracidad_layer.py`
  (veracidad/anti-alucinación).

## Qué se usó en free-ai

Se tomaron **principios públicos**, no código:

1. Pensamiento externado en pasos explícitos.
2. Validación antes de avanzar (no construir sobre un paso vacío/defectuoso).
3. Anti-repetición y parada ante degeneración.
4. Veracidad explícita: si no hay evidencia, no se afirma; se declara
   incertidumbre.

La implementación local es `thinker_layer.py`, una capa clean-room de ~150
líneas para el fallback NCM. **No se copió código GPL-3.0** dentro de free-ai;
se mantiene la atribución y el enlace. Si se quisiera vendorizar el paquete
completo, habría que revisar compatibilidad GPL-3.0-only antes de distribuirlo.

## Qué hace la capa local

- `analyze(text)`: intención (`math`, `identity`, `recall`, `code`, `factual`,
  `chat`), estrategia y confianza.
- `validate(reply, analysis)`: vacío, filler, repetición, matemática,
  recall, diversidad factual, límite de contexto para código.
- `repair(analysis, reply)`: respuesta determinista para matemática, rechazo
  honesto para código, incertidumbre explícita para hechos.
- `decorate`: prefijo `i'm not sure, but ...` en factuales de baja confianza.
- `trace`: pasos y notas que viajan en `gateway.thinker` de la respuesta.

## Límites honestos

- NCM-Instruct-725M es un modelo de hobby (persona "neko"), 128 tokens,
  inglés/minúsculas, conocimiento factual débil, licencia **CC BY-NC-SA 4.0**
  (no comercial).
- La capa thinker no convierte a NCM en un modelo de código ni de hechos:
  evita respuestas inventadas y mejora matemática simple, nada más.
- No sustituye al pipeline de investigación de `jmbigi/thinker` (búsqueda,
  citas, claims, evaluación de evidencia); eso requiere proveedores y
  búsqueda reales.
