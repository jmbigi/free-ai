# 2026-11-08: integración real de jmbigi/thinker

## Qué se incorporó

Se clonó `https://github.com/jmbigi/thinker` en `/home/kubuntu/thinker` y se
creó un servicio local que importa sus capas reales:

- `pensamiento_layer.DeepResearchThinkingLayer` (7 pasos).
- `veracidad_layer.VeracityLayer` (veracidad estricta).
- `llm_providers.ForthtradeGatewayLLM` apuntando al gateway local
  (`http://127.0.0.1:8000/v1`, modelo `auto`).
- `MockLLM` para pruebas deterministas.

Archivos:

- `local/thinker/thinker_service.py` (FastAPI, puerto 11437).
- `local/thinker/README.md`.
- `deploy/thinker.service.example`.
- Gateway: `POST /v1/think` y `POST /v1/verify` con auth, proxy al servicio.

## Evidencia

- `thinker.service`: **active/enabled** en `127.0.0.1:11437`.
- `GET /health`: OK, capas `DeepResearchThinkingLayer` + `VeracityLayer`.
- `POST /v1/think` con `provider="mock"`, `max_steps=7`: **valid=true,
  step_count=7, simulated=true**.
- `POST /v1/think` con `provider="gateway"`, `model="auto"`, `max_steps=1`:
  **HTTP 200 en 17.2 s**, `valid=true`, `simulated=false`.
- `POST /v1/verify` con claim y sin evidencia: **not_addressed, confianza 0**;
  no fabrica `supported`.
- Gateway sin auth: **401**; con auth: 200.
- `kimi doctor` y prueba KimiCode local siguen OK.

## Límites

- `provider="gateway"` hace una llamada LLM por paso; 7 pasos pueden ser lentos
  o chocar con rate limits free-tier. El servicio permite `max_steps` para
  pruebas y `provider="mock"` para verificar mecánica sin red.
- La capa thinker estructura y valida; no garantiza verdad ni sustituye
  evidencia. `/v1/verify` sin evidencia es honesto: `not_addressed`.
- El clon de thinker es externo (GPL-3.0-only); el repo solo contiene el puente
  y la documentación, no vendoriza el paquete.
- `ncm-lm1b` sigue siendo unconditional y no se usa para thinker/chat.
