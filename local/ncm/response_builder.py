"""Pure OpenAI-compatible response construction for the local NCM server.

Kept free of torch/fastapi imports so the response contract can be unit-tested
without loading the model. The server generates all ``n`` samples; these
helpers must expose all of them and report ``tokens_per_sample * n`` tokens.
"""
from __future__ import annotations

from typing import Any


def _validate_texts(texts: list[str], tokens_per_sample: int) -> None:
    if not isinstance(texts, list) or not texts:
        raise ValueError("texts must be a non-empty list")
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("every text must be a non-empty string")
    if tokens_per_sample <= 0:
        raise ValueError("tokens_per_sample must be positive")


def _gateway(latency_ms: int, tokens_per_sample: int, samples: int) -> dict[str, Any]:
    return {
        "local": True,
        "experimental": True,
        "unconditional": True,
        "prompt_ignored": True,
        "fixed_length": tokens_per_sample,
        "buffered_stream": True,
        "batch": samples,
        "samples": samples,
        "latency_ms": latency_ms,
    }


def build_completion(
    *,
    model_id: str,
    texts: list[str],
    latency_ms: int,
    completion_id: str,
    created: int,
    tokens_per_sample: int,
) -> dict[str, Any]:
    """Build a non-streaming chat.completion with one choice per generated text."""
    _validate_texts(texts, tokens_per_sample)
    samples = len(texts)
    total_tokens = samples * tokens_per_sample
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model_id,
        "choices": [
            {
                "index": index,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
            for index, text in enumerate(texts)
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": total_tokens,
            "total_tokens": total_tokens,
        },
        "provider": "ncm-lm1b",
        "gateway": _gateway(latency_ms, tokens_per_sample, samples),
    }


def build_stream_chunks(
    *,
    model_id: str,
    texts: list[str],
    latency_ms: int,
    completion_id: str,
    created: int,
    tokens_per_sample: int,
) -> list[dict[str, Any]]:
    """Build buffered SSE chunks for every choice, including a final stop chunk.

    NCM is not a token-streaming model: the first chunk already contains the
    complete text for that choice. The chunks are still valid OpenAI-style
    ``chat.completion.chunk`` objects.
    """
    _validate_texts(texts, tokens_per_sample)
    samples = len(texts)
    total_tokens = samples * tokens_per_sample
    gateway = _gateway(latency_ms, tokens_per_sample, samples)
    chunks: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        chunks.append(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [
                    {
                        "index": index,
                        "delta": {"role": "assistant", "content": text},
                        "finish_reason": None,
                    }
                ],
                "gateway": gateway,
            }
        )
    chunks.append(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_id,
            "choices": [
                {"index": index, "delta": {}, "finish_reason": "stop"}
                for index in range(samples)
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
            "gateway": gateway,
        }
    )
    return chunks
