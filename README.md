# Free AI Gateway

Gateway **OpenAI-compatible** protegido por **1 API key** (`API_KEY` en `.env`) que enruta a proveedores/cuentas de IA con opciones gratuitas disponibles.

## Estado de este despliegue (verificado)
- `GET /v1/providers` con `Authorization: Bearer <API_KEY>`: detecta proveedores activos desde `.env` (incluye los que agregues).
- `POST /v1/chat/completions` con `model: "auto"`: **responde OK** usando fallback automático.
- Cuentas agregadas en `.env`:
  - `OPENROUTER_API_KEY` → proveedor **activo**. Nota: las rutas `:free/openrouter/free` dependen de la cuota diaria/estado de la cuenta OpenRouter; si están agotadas, el gateway devuelve el error real o `auto` hace fallback a otro proveedor disponible.
  - `HUGGINGFACE_API_KEY` / `HUGGING_FACE_API_KEY` → proveedor **activo**. Nota: Hugging Face Router puede requerir créditos prepagados/proveedores habilitados según el modelo; si no hay créditos/ruta, el gateway devuelve el error real o `auto` hace fallback.
- Sin depender de upstream pagado: `pollinations/*` funciona como proveedor anónimo gratuito (con límites por IP/proveedor).

## Realidad operativa
No existe inferencia avanzada verdaderamente **ilimitada** y gratis sin restricciones. Los tiers gratuitos tienen rate limits, cuotas diarias, créditos o condiciones. Este gateway:
1. protege acceso con tu `API_KEY`;
2. expone una API OpenAI-compatible única;
3. agrega **todas las fuentes gratuitas configurables** desde `.env`;
4. usa `model=auto` para fallback entre proveedores disponibles cuando uno falla por cuota/límite.

## Ejecutar
```bash
cd /home/admin/free-ai
./run.sh
# UI: http://localhost:8000  | Docs: /docs | Health: /health
```

## Autenticación (clientes del gateway)
Usa la clave de `.env`:
- `Authorization: Bearer <API_KEY>` (recomendado)
- `x-api-key: <API_KEY>`
- `?key=<API_KEY>` (solo pruebas)

## Uso OpenAI-compatible
```bash
export API_KEY="$(grep '^API_KEY=' .env | cut -d= -f2-)"
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Responde solo: OK"}],"max_tokens":32}'
```

Modelo directo (si el proveedor/cuenta tiene capacidad):
```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"pollinations/openai-fast","messages":[{"role":"user","content":"Hola"}]}'
```

Streaming SSE:
```bash
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"auto","stream":true,"messages":[{"role":"user","content":"Cuenta hasta 5"}]}'
```

## Endpoints
- `GET /` — playground UI
- `GET /health` — estado, proveedores activos
- `GET /docs` — Swagger
- `GET /v1/models` — catálogo (auth)
- `GET /v1/providers` — estado de proveedores/cuentas (auth)
- `POST /v1/chat/completions` — chat OpenAI-compatible, `auto` + fallback (auth)

## Agregar más cuentas gratuitas
Edita `.env` (el gateway las detecta en vivo):
```env
API_KEY=...
OPENROUTER_API_KEY=...
HUGGINGFACE_API_KEY=...   # o HUGGING_FACE_API_KEY / HF_TOKEN
GROQ_API_KEY=
GEMINI_API_KEY=
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_API_TOKEN=...
NVIDIA_API_KEY=
MISTRAL_API_KEY=
SAMBANOVA_API_KEY=
CEREBRAS_API_KEY=
TOGETHER_API_KEY=
COHERE_API_KEY=
```
Luego consulta `/v1/providers` y `/v1/models`. Puedes pasar `proveedor/modelo` directo (ej. `openrouter/openrouter/free`, `huggingface/openai/gpt-oss-20b`) o usar `auto`.
