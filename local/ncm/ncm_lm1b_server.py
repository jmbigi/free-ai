"""OpenAI-compatible local server for the official NCM LM1B-large checkpoint.

Honest behavior: LM1B-large is an UNCONDITIONAL generator. It ignores chat
messages and always produces a 128-token news-style sample. It is exposed for
experimentation, not as a chat fallback. NCM cannot stream: this server emits a
buffered SSE chunk after the full generation.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
import sys
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from omegaconf import OmegaConf
from pydantic import BaseModel, Field

ROOT = os.environ.get("NCM_HOME", "/home/kubuntu/ncm")
CONFIG = os.environ.get("NCM_CONFIG", os.path.join(ROOT, "config/eval/lm1b-large.yaml"))
CKPT = os.environ.get("NCM_CKPT", os.path.join(ROOT, "artifacts/lm1b/large"))
sys.path.insert(0, ROOT)

from models.next_concept import NextConceptTransformer
from tokenization.vqvae_tokenizer import VQVAETokenizer

MODEL_ID = "ncm-lm1b-large"
TOKENS_PER_SAMPLE = 128

app = FastAPI(title="NCM LM1B-large local", version="0.1.0")
_cfg = None
_tk = None
_net = None
_l0_p = None
_allow = None
_eos = None
_pad = None
_generation: dict[str, Any] = {}
_params = 0
_vram_peak = 0.0
load_s: float | None = None
_lock = asyncio.Lock()


class ChatMessage(BaseModel):
    role: str
    content: Any = ""


class ChatRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[ChatMessage] = Field(default_factory=list)
    n: int = 1
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int = 0
    stream: bool = False


def pick_tokens(logits: torch.Tensor, *, freq: float, mu: float,
                adj: list[float] | None, allow: torch.Tensor | None) -> torch.Tensor:
    if freq <= 0 and not adj:
        return logits.argmax(-1)
    B, T, V = logits.shape
    lg = logits.double()
    allow_v = (allow[:V] * T)[None, :] if allow is not None else None
    al = adj[0] if adj else 0.0
    aw = int(adj[1]) if adj and len(adj) > 1 else 1
    ad = adj[2] if adj and len(adj) > 2 else 1.0
    cnt = torch.zeros(B, V, dtype=torch.float64, device=lg.device)
    out = torch.empty(B, T, dtype=torch.long, device=lg.device)
    hist: list[torch.Tensor] = []
    for t in range(T):
        step = lg[:, t, :].clone()
        if freq > 0:
            excess = (cnt - allow_v).clamp_min(0.0) if allow_v is not None else cnt
            step -= freq * excess
            if mu > 0 and allow_v is not None:
                step += mu * ((T - t) / T) * (allow_v - cnt).clamp_min(0.0)
        for j, h in enumerate(reversed(hist[-aw:])):
            step.scatter_add_(1, h[:, None], torch.full((B, 1), -al * ad ** j, dtype=torch.float64, device=lg.device))
        p = step.argmax(-1)
        out[:, t] = p
        hist.append(p)
        cnt.scatter_add_(1, p[:, None], torch.ones(B, 1, dtype=torch.float64, device=lg.device))
    return out


def _load() -> None:
    global _cfg, _tk, _net, _l0_p, _allow, _eos, _pad, _generation, _params, _vram_peak, load_s
    started = time.time()
    cfg = OmegaConf.load(CONFIG)
    cfg.tokenizer.vqvae.checkpoint_path = os.path.join(CKPT, cfg.checkpoints.tokenizer)
    tk = VQVAETokenizer.from_config(cfg.tokenizer)
    tk.vqvae = tk.vqvae.cuda().eval()
    net = NextConceptTransformer(vqvae_local=tk.vqvae, config=cfg.model).cuda()
    sd = torch.load(os.path.join(CKPT, cfg.checkpoints.generator), map_location="cpu", weights_only=False)
    net.load_state_dict(sd["model"], strict=True)
    net.eval()
    _cfg, _tk, _net = cfg, tk, net
    _generation = dict(cfg.generation)
    _l0_p = sd["inference"]["level0_unigram"].float().cuda()
    _allow = sd["inference"]["token_unigram"].double().cuda()
    _eos = tk.pre_tokenizer.eos_token_id
    _pad = tk.pre_tokenizer.pad_token_id
    _params = sum(p.numel() for p in net.parameters())
    _vram_peak = torch.cuda.max_memory_allocated() / (1024 * 1024)
    load_s = time.time() - started


def _decode(ids: list[int]) -> str:
    out = [t for t in ids if t not in (_eos, _pad)]
    return _tk.pre_tokenizer.decode(out, skip_special_tokens=True).strip()


def _generate_sync(n: int, temperature: float | None, top_p: float | None, seed: int) -> dict[str, Any]:
    n = max(1, min(4, int(n or 1)))
    temp = float(temperature if temperature is not None else _generation.get("temperature", 1.0))
    top_p = float(top_p if top_p is not None else _generation.get("top_p", 1.0))
    top_k = int(_generation.get("top_k", 0) or 0)
    freq = float(_generation.get("frequency_penalty", 0) or 0)
    mu = float(_generation.get("frequency_deficit", 0) or 0)
    adj_s = str(_generation.get("adjacency_penalty", "") or "")
    adj = [float(v) for v in adj_s.split(",")] if adj_s else None
    torch.manual_seed(int(seed or 0))
    started = time.time()
    with torch.no_grad():
        l0 = torch.multinomial(_l0_p.cpu(), n * int(_tk.vqvae.vq.levels[0]), replacement=True)
        l0 = l0.view(n, int(_tk.vqvae.vq.levels[0])).cuda()
        x = torch.full((n, 1), _eos, device="cuda")
        g = _net.generate(l0, x, temperature=temp, top_k=top_k, top_p=top_p,
                          cfg_scale=0.0, cfg_null_eos=_eos)
        _, zl = _tk.vqvae.vq.idx_to_zhats(g, return_zlevels=True)
        ids = pick_tokens(_tk.vqvae.decoder(zl[-1]), freq=freq, mu=mu,
                          adj=adj, allow=_allow).tolist()
    torch.cuda.synchronize()
    texts = [_decode(row) for row in ids]
    return {
        "texts": texts,
        "latency_ms": int((time.time() - started) * 1000),
        "n": n,
        "temperature": temp,
        "top_p": top_p,
    }


async def _run(req: ChatRequest) -> dict[str, Any]:
    if _net is None:
        raise HTTPException(status_code=503, detail="NCM LM1B-large not loaded")
    async with _lock:
        try:
            return await asyncio.to_thread(
                _generate_sync, req.n, req.temperature, req.top_p, req.seed,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"NCM generation failed: {exc}") from exc


def _response(req: ChatRequest, result: dict[str, Any]) -> dict[str, Any]:
    text = result["texts"][0]
    return {
        "id": f"chatcmpl-ncmlm1b-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": TOKENS_PER_SAMPLE,
                  "total_tokens": TOKENS_PER_SAMPLE},
        "provider": "ncm-lm1b",
        "gateway": {
            "local": True,
            "experimental": True,
            "unconditional": True,
            "prompt_ignored": True,
            "fixed_length": TOKENS_PER_SAMPLE,
            "buffered_stream": True,
            "latency_ms": result["latency_ms"],
        },
    }


@app.on_event("startup")
def _startup() -> None:
    _load()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok" if _net is not None else "loading",
        "model": MODEL_ID,
        "loaded": _net is not None,
        "params": _params,
        "load_s": round(load_s, 3) if load_s else None,
        "vram_mb": round(_vram_peak, 1) if _vram_peak else None,
        "unconditional": True,
        "prompt_ignored": True,
        "fixed_length": TOKENS_PER_SAMPLE,
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {"object": "list", "data": [{
        "id": MODEL_ID, "object": "model", "created": 0, "owned_by": "local",
        "provider": "ncm-lm1b", "free": True,
        "note": "Official NCM LM1B-large (725M), unconditional, fixed 128-token samples; ignores prompts.",
    }]}


@app.post("/v1/chat/completions")
async def chat(req: ChatRequest):
    result = await _run(req)
    body = _response(req, result)
    if not req.stream:
        return body

    async def gen():
        chunk = {
            "id": body["id"], "object": "chat.completion.chunk",
            "created": body["created"], "model": MODEL_ID,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": result["texts"][0]},
                         "finish_reason": None}],
            "gateway": body["gateway"],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
        final = {"id": body["id"], "object": "chat.completion.chunk",
                 "created": body["created"], "model": MODEL_ID,
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
