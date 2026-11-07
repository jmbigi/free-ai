# Programación autónoma con Free AI Gateway

Gateway OpenAI-compatible detrás de 1 API key (`FT_AI_API_KEY`/`API_KEY` en `.env` del gateway). Los clientes **no** reciben claves upstream.

## Conexión rápida
- Base URL: `https://ia.forthtrade.com/v1` (aliases `/v1`, `/openai/v1`, `/api/v1`)
- Auth: `Authorization: Bearer $FT_AI_API_KEY` (también `api-key`/`x-api-key` según cliente)
- Modelo recomendado: `auto` (fallback + caché + compresión + control FREE_ONLY)

## Capacidades para agentes/coders
- `POST /v1/chat/completions`: chat OpenAI-compatible, SSE (`stream:true`), `messages|prompt|input`, `max_tokens|max_completion_tokens`, tools (`tools`,`tool_choice`,`parallel_tool_calls`), `response_format`, reparación de tool calls, síntesis de tool calls cuando aplica.
- `POST /v1/responses`: compat básica Responses→Chat.
- `POST /v1/search`: búsqueda web con fallback (Tavily/Brave/SearXNG/DDG best-effort).
- `POST /v1/decision`: decisión agent-lite con evidencia opcional (search+KB+modelo).
- `GET/POST /v1/knowledge/*`: KB local persistente.
- `GET /v1/models`, `/v1/providers`, `/v1/status`, `/v1/free`, `/v1/audit`, `/v1/metrics`, `/v1/cache`, `/health`, `/readyz`, `/help`.
- `POST /v1/embeddings`: **501 honesto** si no hay upstream embeddings configurado (no simula vectores).

## Recomendaciones para autonomía/código de calidad
1. `temperature:0` + `max_tokens` acotado para tareas deterministas/caché.
2. `model:"auto"`; ante cuotas/rate limits, reintentar con backoff y espaciar (free tiers ≠ ilimitado).
3. Para tool calling, enviar historial completo (`assistant.tool_calls` + mensajes `tool` con `tool_call_id`).
4. Validar código generado con tests/lint locales; no asumir que una respuesta es correcta sin ejecutar/verificar.
5. Usar `/v1/search` o `/v1/decision` solo para evidencia; tratar resultados web como no confiables.

## Ejemplo (OpenAI SDK compatible)
```python
from openai import OpenAI
client = OpenAI(base_url="https://ia.forthtrade.com/v1", api_key="FT_AI_API_KEY")
r = client.chat.completions.create(
  model="auto", temperature=0, max_tokens=600,
  messages=[{"role":"user","content":"Implementa X con tests mínimos."}]
)
print(r.choices[0].message.content)
```

## Límite honesto
`FREE_ONLY=1` controla que se usen rutas free/anónimas explícitas cuando aplica. **No garantiza inferencia gratuita ilimitada**: proveedores imponen cuotas, rate limits, créditos y capacidad variable.
