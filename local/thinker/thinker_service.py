"""Local service exposing the real jmbigi/thinker layers.

It imports `DeepResearchThinkingLayer` and `VeracityLayer` from the cloned
thinker repository (THINKER_HOME) and uses `ForthtradeGatewayLLM` pointing to
the local free-ai gateway by default. It is a separate service because the
thinker repository has its own dependency set.

Honest behavior:
- `provider="gateway"` performs real LLM calls (default `auto`).
- `provider="mock"` uses MockLLM and is explicitly marked `simulated=true`.
- `/v1/verify` without evidence returns `not_addressed`, never a fabricated
  "supported" verdict.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

THINKER_HOME = os.environ.get("THINKER_HOME", "/home/kubuntu/thinker")
if THINKER_HOME not in sys.path:
    sys.path.insert(0, THINKER_HOME)

from pensamiento_layer import DeepResearchThinkingLayer  # noqa: E402
from veracidad_layer import VeracityLayer  # noqa: E402
from llm_providers import ForthtradeGatewayLLM, MockLLM  # noqa: E402

app = FastAPI(title="jmbigi/thinker local bridge", version="0.1.0")
GATEWAY_BASE_URL = os.environ.get("FORTHTRADE_BASE_URL", "http://127.0.0.1:8000/v1")
GATEWAY_MODEL = os.environ.get("FORTHTRADE_MODEL", "auto")
LLM_TIMEOUT = float(os.environ.get("THINKER_LLM_TIMEOUT", "45"))
REQUIRED_STEPS = [
    "analysis",
    "plan",
    "search_strategy",
    "search_results",
    "claim_extraction",
    "evidence_eval",
    "synthesis",
]


class ThinkRequest(BaseModel):
    prompt: str = Field(min_length=1)
    provider: str = "gateway"  # gateway | mock
    model: str | None = None
    # Accepted for client compatibility, but the bridge always runs all 7 steps.
    max_steps: int = 7
    use_tot: bool = False


class VerifyRequest(BaseModel):
    claim: str | None = None
    response_text: str | None = None
    mode: str = "strict"
    permitir_sintetica: bool = False
    justificacion_sintetica: str = ""


def _provider(req: ThinkRequest):
    if req.provider == "mock":
        return MockLLM(), "mock", True
    if req.provider != "gateway":
        raise HTTPException(status_code=400, detail="provider must be 'gateway' or 'mock'")
    llm = ForthtradeGatewayLLM(
        model=req.model or GATEWAY_MODEL,
        base_url=GATEWAY_BASE_URL,
        timeout=LLM_TIMEOUT,
    )
    return llm, req.model or GATEWAY_MODEL, False


def _verdict_dict(v) -> dict[str, Any]:
    ev = v.evidencia
    kind = getattr(ev.kind, "value", str(ev.kind))
    return {
        "afirmacion": v.afirmacion,
        "verdict": v.verdict,
        "confianza": v.confianza,
        "reasoning": v.reasoning,
        "evidencia": {"kind": kind, "source": ev.source, "detail": ev.detail},
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "thinker-bridge",
        "thinker_home": THINKER_HOME,
        "gateway_base_url": GATEWAY_BASE_URL,
        "gateway_model": GATEWAY_MODEL,
        "llm_timeout_s": LLM_TIMEOUT,
        "layers": ["DeepResearchThinkingLayer", "VeracityLayer"],
        "steps_required": REQUIRED_STEPS,
    }


@app.post("/v1/think")
def think(req: ThinkRequest) -> dict[str, Any]:
    llm, model, simulated = _provider(req)
    started = time.time()
    layer = DeepResearchThinkingLayer(llm_provider=llm, name="free-ai-thinker")
    # Mandatory 7-step pipeline: never reduced by a client request.
    layer.max_steps = len(REQUIRED_STEPS)
    try:
        result = layer.think_tot(req.prompt) if req.use_tot else layer.think(req.prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"thinker failed: {exc}") from exc
    return {
        "object": "thinker.result",
        "prompt": req.prompt,
        "provider": req.provider,
        "model": model,
        "simulated": simulated,
        "duration_ms": int((time.time() - started) * 1000),
        "valid": bool(result.get("valid")),
        "confidence": result.get("confidence"),
        "steps_expected": len(REQUIRED_STEPS),
        "steps_declared": REQUIRED_STEPS,
        "step_count": result.get("step_count"),
        "steps": result.get("steps") or [],
        "thought": result.get("thought"),
        "decision": result.get("decision"),
        "error": result.get("error"),
    }


@app.post("/v1/verify")
def verify(req: VerifyRequest) -> dict[str, Any]:
    if not req.claim and not req.response_text:
        raise HTTPException(status_code=400, detail="provide claim or response_text")
    try:
        layer = VeracityLayer(
            mode=req.mode,
            permitir_sintetica=req.permitir_sintetica,
            justificacion_sintetica=req.justificacion_sintetica,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.response_text:
        try:
            text, verdicts = layer.proteger_respuesta(req.response_text)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"veracity failed: {exc}") from exc
        return {
            "object": "veracity.result",
            "mode": req.mode,
            "protected_text": text,
            "verdicts": [_verdict_dict(v) for v in verdicts],
        }
    try:
        verdict = layer.verificar(req.claim or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"veracity failed: {exc}") from exc
    return {"object": "veracity.result", "mode": req.mode, "verdicts": [_verdict_dict(verdict)]}
