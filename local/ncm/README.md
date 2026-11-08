# NCM LM1B-large local server

OpenAI-compatible local server for the official NCM **LM1B-large** checkpoint
(725M). It is an **unconditional** generator: it ignores prompts and always
produces a fixed 128-token news-style sample. It is exposed as an explicit
experimental model, **not** as an `auto` chat fallback.

## Requirements

- The HazyResearch NCM checkout and checkpoints outside this repo, by default
  `/home/kubuntu/ncm` (override with `NCM_HOME`).
- `artifacts/lm1b/large/generator.pt`, `artifacts/lm1b/tokenizer.pt` and the
  official `config/eval/lm1b-large.yaml`.
- A Python env with `torch` CUDA and the NCM requirements (by default
  `/home/kubuntu/ncm/.venv`).

## Run

```bash
NCM_HOME=/home/kubuntu/ncm \
  /home/kubuntu/ncm/.venv/bin/python -m uvicorn ncm_lm1b_server:app \
  --host 127.0.0.1 --port 11436
```

Health: `GET http://127.0.0.1:11436/health`
Models: `GET http://127.0.0.1:11436/v1/models`
Chat-compatible endpoint: `POST /v1/chat/completions` (prompt ignored).

Service example: `deploy/ncm-lm1b.service.example`.

## Honest limits

- Unconditional: it cannot answer or follow a chat prompt.
- Fixed output length: 128 tokens.
- No true streaming: the SSE is buffered until generation finishes.
- 725M parameters; ~3.4 GB VRAM; fits an 8 GB GPU.
- Use `NCM_LM1B_ENABLED=1` in the gateway to expose it as
  `ncm-lm1b/ncm-lm1b-large`; it is deliberately absent from `auto`.
