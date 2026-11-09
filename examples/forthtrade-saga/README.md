# Orquestador SAGA Determinista

**Propósito**: Demostrar un orquestador de transacciones SAGA para pagos, inventario y envíos, con persistencia local, idempotencia, reintentos, compensaciones inversas y recuperación ante fallos.

> ⚠️ **Aviso**: Es una simulación local en proceso, no un servicio de producción. Usa SQLite en archivos locales, no microservicios reales ni red.

---

## Arquitectura y Archivos

- `saga_core.py` — Núcleo: `Orchestrator`, `Store`, `EffectStore`, servicios (Payment, Inventory, Shipping), `FaultPlan` para inyección de fallos.
- `saga_cli.py` — CLI con subcomandos: `demo`, `audit`, `dlq`, `recover`.
- `tests/test_saga.py` — 11 tests unitarios que validan todos los escenarios.
- Bases SQLite por servicio (`payment.db`, `inventory.db`, `shipping.db`) y orquestador (`orchestrator.db`) en el directorio de datos (`data/` por defecto o `SAGA_DATA_DIR`).

---

## Estados de la SAGA

`PENDING` → `RUNNING` → `COMPLETED`
Fallos: `COMPENSATING` → `COMPENSATED` / `MANUAL_INTERVENTION` / `FAILED`

---

## Garantías Implementadas

- **Persistencia WAL**: `PRAGMA journal_mode=WAL` en todas las conexiones.
- **Idempotencia dual**: por `request_id` (crea/recupera SAGA) y por `saga_id:step` en `EffectStore` (clave única + `BEGIN IMMEDIATE`).
- **Reintentos**: hasta `max_attempts` (def. 3) con backoff configurable.
- **Compensaciones inversas**: orden inverso a los pasos forward; cada una con sus reintentos.
- **Crash/Recovery**: `recover(force=True)` reclama SAGAs `PENDING`/`RUNNING` con lease expirado o forzado y reanuda desde el último paso confirmado.
- **Claims atómicos**: `BEGIN IMMEDIATE` + `UPDATE ... WHERE status IN (?,?) AND (lease=0 OR lease<now)`.
- **DLQ**: errores irreversibles van a tabla `dlq` (saga_id, step, error, ts).
- **Auditoría append-only**: tabla `events` (step, action=fwd/fail/comp, result, attempt, ts).
- **Concurrencia**: `run_many(rids, workers=N)` usa `ThreadPoolExecutor`.

---

## Escenarios CLI (subcomando `demo --scenario`)

| Escenario | Descripción | Estado final esperado |
|-----------|-------------|----------------------|
| `happy` | Flujo completo sin fallos | `COMPLETED` |
| `payment_fail` | Pago falla permanente (3 intentos) | `COMPENSATED` |
| `inventory_fail` | Inventario falla tras pago OK | `COMPENSATED` |
| `shipping_fail` | Envío falla tras pago + inventario | `COMPENSATED` |
| `compensation_fail` | Envío falla + release inventario falla | `MANUAL_INTERVENTION` |
| `retry_success` | Inventario falla 1 vez, 2º intento OK | `COMPLETED` |
| `crash_recovery` | Crash tras `payment.reserve`; `recover(force=True)` completa | `RUNNING` → `COMPLETED` |
| `duplicate` | Mismo `request_id` dos veces | 3 efectos totales (idempotente) |
| `concurrent` | 8 SAGAs paralelas, 4 workers | Todas `COMPLETED` |

Comandos adicionales:
- `audit <saga_id>` — imprime historial de eventos.
- `dlq` — lista Dead Letter Queue global.
- `recover [--force]` — recupera SAGAs pendientes.

---

## Cómo Ejecutar

```bash
# Tests (11 pasan)
python3 -m unittest discover -s tests -v

# Demos (cada uno crea su directorio demo_<scenario> en data/)
python3 saga_cli.py demo --scenario happy --data-dir data
python3 saga_cli.py demo --scenario payment_fail --data-dir data
python3 saga_cli.py demo --scenario inventory_fail --data-dir data
python3 saga_cli.py demo --scenario shipping_fail --data-dir data
python3 saga_cli.py demo --scenario compensation_fail --data-dir data
python3 saga_cli.py demo --scenario retry_success --data-dir data
python3 saga_cli.py demo --scenario crash_recovery --data-dir data
python3 saga_cli.py demo --scenario duplicate --data-dir data
python3 saga_cli.py demo --scenario concurrent --data-dir data

# Utilidades
python3 saga_cli.py audit <saga_id> --data-dir data
python3 saga_cli.py dlq --data-dir data
python3 saga_cli.py recover --force --data-dir data
```

---

## Resultado Real Verificado

- **Tests**: 11/11 pasan (`test_1_happy_path` … `test_11_audit_invariants`).
- **Demos**: 9/9 salen con código 0.
- `crash_recovery`: primera corrida deja estado `RUNNING`; tras `recover(force=True)` pasa a `COMPLETED`.
- `duplicate`: dos llamadas con mismo `request_id` dejan **3 efectos** totales (uno por servicio).

---

## Límites Conocidos

- Simulación **en proceso** (hilos), no microservicios reales ni red.
- SQLite local (archivos), no base de datos distribuida.
- No garantiza *exactly-once* de red; idempotencia solo a nivel de clave local.
- Sin TLS, autenticación, HTTP, serialización JSON sobre red.
- No benchmark de producción ni prueba a escala (cientos de miles de SAGAs).
- `FaultPlan` es determinista para tests/demos; no modelo de fallos realista.

---

## Autoría

Código generado por **ForthTrade IA** a través de **KimiCode**; el operador solo orquestó prompts y ejecutó tests.
