# 2026-11-08: regla anti-bloqueo y anti-ciclos en el fallback

## Problema observado

- Con cuota free agotada, `auto` recorría varios modelos del mismo proveedor (p. ej. 6 rutas `:free` de OpenRouter) aunque el 429/402 fuera de cuenta/cuota y afectara a todas.
- `_throttle` podía dormir hasta `FREE_TIER_MAX_WAIT` (60s) dentro del request; el presupuesto de 45s no limitaba esa espera ni la llamada upstream.
- Ante un 400/422 de request inválido, se seguía probando otros proveedores: ciclos inútiles que consumían cuota.
- `ProviderError` no transportaba `Retry-After`, así que `_cooldown_for` nunca podía honrarlo.
- Los streams usaban `httpx.Timeout(None)`: un upstream colgado podía bloquear indefinidamente.
- El antiguo bucle añadía intentos falsos (`provider=gateway, model=wait`) y esperaba cooldowns de hasta 3s; el conteo de intentos se contaminaba.

## Regla implementada

1. **Presupuesto único por request** (`REQUEST_BUDGET=45`, acotado también por `REQUEST_TIMEOUT`). Cada llamada se ejecuta con `asyncio.wait_for(..., remaining)`.
2. **Throttle con deadline**: si la espera de free-tier no cabe en el presupuesto, se devuelve 429 con `Retry-After` y se hace fallback; nunca se duerme para fallar después. La contención del lock se limita a 2s.
3. **Clasificación de fallos** (`terminal`, `provider`, `model`, `transient`):
   - `terminal` (400/422 de request inválido): se corta el request, no se reintenta.
   - `provider` (401/403/402/429): se saltan todos los modelos del proveedor y se abre breaker.
   - `model` (404): se prueba otro modelo.
   - `transient` (5xx/timeout/red): fallback + umbral de breaker.
4. **Circuit breaker por proveedor** (`PROVIDER_BREAKER_THRESHOLD=3`, `PROVIDER_BREAKER_COOLDOWN=60`):
   - cuota/auth abre de inmediato, con `Retry-After` si existe (401/403 mínimo 300s);
   - transitorios abren tras 3 fallos, con backoff exponencial y jitter, cap 120s.
5. **Plan acotado**: máximo 2 modelos por proveedor y sin proveedores con breaker abierto; se elimina el bucle `while` y los intentos falsos.
6. **`Retry-After` RFC 9110** parseado en todos los providers (segundos o HTTP-date) y propagado al cliente.
7. **Streaming**: timeout de lectura por chunk, breaker por proveedor y salto inmediato si el modelo está en cooldown; si ya hubo salida parcial no se reintenta.

## Evidencia de verificación

- `tests_router_unit.py`: 13 tests (clasificación, Retry-After, breaker, plan, throttle) → `OK`.
- Caso real: segunda llamada a Pollinations dentro de 46s → falla en ~0.001s con 429/`Retry-After=46` en vez de dormir 46s; el router salta el proveedor.
- El test de contención de lock destapó y corrigió un bug: `_throttle` liberaba un lock que no había adquirido al expirar la espera.
- Estado expuesto en `/v1/status` → `runtime.provider_breakers`.

## Referencias

- AWS Architecture Blog, *Exponential Backoff and Jitter*: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- Google SRE Book, *Handling Overload*: https://sre.google/sre-book/handling-overload/
- Azure Architecture Center, *Circuit Breaker pattern*: https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker
- RFC 9110 §10.2.3, *Retry-After*: https://www.rfc-editor.org/rfc/rfc9110#section-10.2.3

## Limitación honesta

El breaker y el presupuesto evitan bloqueos/ciclos, pero **no crean cuota gratuita**: si todas las fuentes free están agotadas, el gateway responde rápido con 502/`Retry-After` en lugar de colgarse. Gratis controlado ≠ ilimitado.
