# jmbigi/thinker bridge

This directory exposes the **real** `jmbigi/thinker` layers as a local
OpenAI-independent service:

- `DeepResearchThinkingLayer` (7-step structured thinking).
- `VeracityLayer` (strict evidence/veracity verdicts).

It imports the cloned repository from `THINKER_HOME` (default
`/home/kubuntu/thinker`) and uses `ForthtradeGatewayLLM` against the local
gateway by default (`FORTHTRADE_BASE_URL=http://127.0.0.1:8000/v1`).

## Run

```bash
cd /home/kubuntu/free-ai/local/thinker
THINKER_HOME=/home/kubuntu/thinker \
FORTHTRADE_BASE_URL=http://127.0.0.1:8000/v1 \
  /home/kubuntu/thinker/.venv/bin/python -m uvicorn thinker_service:app \
  --host 127.0.0.1 --port 11437
```

Requires the thinker env (`/home/kubuntu/thinker/.venv`) with
`requirements.txt` + `fastapi` + `uvicorn`.

## Endpoints

- `GET /health`
- `POST /v1/think`:
  `{"prompt": "...", "provider": "gateway|mock", "model": "auto", "max_steps": 7, "use_tot": false}`
- `POST /v1/verify`:
  `{"claim": "...", "mode": "strict"}` or
  `{"response_text": "...", "mode": "query"}`

`provider="mock"` uses the thinker `MockLLM` and is marked `simulated=true`.
Without evidence, `/v1/verify` returns `not_addressed` with confidence 0; it
does not fabricate a `supported` verdict.

## Gateway proxy

With `THINKER_ENABLED=1` and `THINKER_BASE_URL=http://127.0.0.1:11437`, the
gateway exposes authenticated `POST /v1/think` and `POST /v1/verify` and adds
the aliases `/think`, `/openai/v1/think`, `/api/v1/think`, `/verify`,
`/openai/v1/verify`, `/api/v1/verify`.

## Limits

- `provider="gateway"` makes one real LLM call per step (7 by default); on
  free-tier upstreams this can be slow or rate-limited.
- The thinker layer is research-oriented; it does not guarantee truth.
- The real thinker code is an external clone; this repo only contains the
  bridge/service and documentation.
