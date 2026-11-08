#!/usr/bin/env python3
"""Benchmark the local NCM LM1B-large OpenAI-compatible server.

This is a *capacity* benchmark for the active local service, not a fair NCM vs
AR comparison. NCM LM1B-large is unconditional: it ignores prompts and always
generates 128 tokens per sample. The server caps ``n`` at 4 and serializes
generation with an asyncio lock, so batches are measured sequentially.

Run:
    python3 local/ncm/benchmark_ncm.py --repeats 3
    python3 local/ncm/benchmark_ncm.py --batches 1,2,4 --output /tmp/ncm.json

No third-party dependencies. The script fails fast with a clear error if the
service is down or returns an invalid response; it never invents measurements.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOKENS_PER_SAMPLE = 128
MAX_SERVER_BATCH = 4
DEFAULT_BASE_URL = "http://127.0.0.1:11436"
DEFAULT_MODEL = "ncm-lm1b-large"


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile, robust for the small sample counts used here."""
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= p <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    rank = max(1, math.ceil((p / 100.0) * len(ordered)))
    return float(ordered[rank - 1])


def summarize(values: list[float]) -> dict[str, float]:
    """Return a compact latency summary in the same units as the input."""
    if not values:
        raise ValueError("summarize requires at least one value")
    return {
        "count": len(values),
        "min": float(min(values)),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": float(max(values)),
        "mean": float(sum(values) / len(values)),
    }


def parse_batches(raw: str) -> list[int]:
    """Parse comma-separated batch sizes, preserving order and rejecting repeats."""
    batches: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            batch = int(token)
        except ValueError as exc:
            raise ValueError(f"batch must be an integer: {token!r}") from exc
        if not 1 <= batch <= MAX_SERVER_BATCH:
            raise ValueError(
                f"batch {batch} is outside the supported range 1..{MAX_SERVER_BATCH}"
            )
        if batch not in batches:
            batches.append(batch)
    if not batches:
        raise ValueError("at least one batch size is required")
    return batches


def _request_json(
    url: str,
    *,
    timeout: float,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"could not connect to {url}: {exc.reason}. "
            "Is the NCM service running?"
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(f"timeout after {timeout:.1f}s calling {url}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response (HTTP {status}) from {url}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"expected a JSON object from {url}, got {type(parsed).__name__}")
    return parsed


def validate_chat_response(data: dict[str, Any], *, batch: int) -> dict[str, Any]:
    """Validate one response and report the server's usage accounting honestly."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("response choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("response choice has no message object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("response content is empty")

    expected_tokens = batch * TOKENS_PER_SAMPLE
    usage = data.get("usage")
    reported_tokens = None
    if isinstance(usage, dict):
        reported_tokens = usage.get("completion_tokens")
    gateway = data.get("gateway")
    gateway_data = gateway if isinstance(gateway, dict) else {}

    return {
        "choices_count": len(choices),
        "content_chars": len(content),
        "expected_completion_tokens": expected_tokens,
        "reported_completion_tokens": reported_tokens,
        "usage_matches_batch": reported_tokens == expected_tokens,
        "single_choice_for_batch": len(choices) == 1 and batch > 1,
        "prompt_ignored": gateway_data.get("prompt_ignored"),
        "unconditional": gateway_data.get("unconditional"),
        "fixed_length": gateway_data.get("fixed_length"),
    }


def benchmark_case(
    base_url: str,
    *,
    model: str,
    batch: int,
    repeats: int,
    warmup: int,
    timeout: float,
    temperature: float,
    seed: int,
) -> dict[str, Any]:
    """Measure one batch size. Warmups are excluded from the statistics."""
    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "benchmark"}],
        "n": batch,
        "max_tokens": TOKENS_PER_SAMPLE,
        "temperature": temperature,
        "seed": seed,
        "stream": False,
    }

    for _ in range(warmup):
        data = _request_json(url, timeout=timeout, payload=payload)
        validate_chat_response(data, batch=batch)

    latencies_ms: list[float] = []
    checks: list[dict[str, Any]] = []
    for _ in range(repeats):
        started = time.perf_counter()
        data = _request_json(url, timeout=timeout, payload=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies_ms.append(elapsed_ms)
        checks.append(validate_chat_response(data, batch=batch))

    tokens_generated = batch * TOKENS_PER_SAMPLE
    throughputs = [
        tokens_generated / (latency_ms / 1000.0) for latency_ms in latencies_ms
    ]
    first = checks[0]
    return {
        "batch": batch,
        "repeats": repeats,
        "warmup": warmup,
        "tokens_generated_per_request": tokens_generated,
        "latencies_ms": [round(value, 3) for value in latencies_ms],
        "latency_summary_ms": summarize(latencies_ms),
        "throughput_tokens_s": [round(value, 3) for value in throughputs],
        "throughput_summary_tokens_s": summarize(throughputs),
        "response_checks": {
            "all_valid": all(check["content_chars"] > 0 for check in checks),
            "all_usage_match_batch": all(
                check["usage_matches_batch"] for check in checks
            ),
            "choices_count": first["choices_count"],
            "single_choice_for_batch": first["single_choice_for_batch"],
            "prompt_ignored": first["prompt_ignored"],
            "unconditional": first["unconditional"],
            "fixed_length": first["fixed_length"],
            "content_chars": first["content_chars"],
            "reported_completion_tokens": first["reported_completion_tokens"],
            "expected_completion_tokens": first["expected_completion_tokens"],
        },
    }


def build_result(
    *,
    base_url: str,
    model: str,
    health: dict[str, Any],
    batches: list[int],
    repeats: int,
    warmup: int,
    temperature: float,
    seed: int,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "service": {
            "base_url": base_url,
            "model": model,
            "health": health,
        },
        "config": {
            "batches": batches,
            "repeats": repeats,
            "warmup": warmup,
            "temperature": temperature,
            "seed": seed,
            "tokens_per_sample": TOKENS_PER_SAMPLE,
            "max_server_batch": MAX_SERVER_BATCH,
        },
        "cases": cases,
        "limitations": [
            "NCM LM1B-large is unconditional and ignores prompts.",
            "The server caps n at 4 and serializes generation with a lock.",
            "For n > 1 the server generates n samples but returns only the first choice and reports 128 completion tokens; this benchmark computes tokens as 128*n and records the mismatch.",
            "This is a local RTX 3070 Laptop 8 GB capacity measurement, not a fair NCM vs AR comparison.",
            "No energy, Nsight Compute, H100, NCP or Cola2 measurements are included.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark the local NCM LM1B-large OpenAI-compatible server."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--batches",
        default="1,2,4",
        help=f"comma-separated batch sizes (1..{MAX_SERVER_BATCH})",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the complete JSON result instead of a short report",
    )
    args = parser.parse_args(argv)

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.warmup < 0:
        parser.error("--warmup cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        batches = parse_batches(args.batches)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        health = _request_json(
            args.base_url.rstrip("/") + "/health", timeout=args.timeout
        )
        if health.get("status") != "ok" or health.get("loaded") is not True:
            raise RuntimeError(f"NCM service is not ready: {health}")

        if not args.json:
            print(f"NCM local benchmark: {args.base_url}")
            print(
                "service: "
                f"params={health.get('params')} "
                f"vram_mb={health.get('vram_mb')} "
                f"load_s={health.get('load_s')}"
            )
            print(
                f"config: model={args.model} batches={batches} "
                f"repeats={args.repeats} warmup={args.warmup}"
            )
            print()

        cases: list[dict[str, Any]] = []
        for batch in batches:
            case = benchmark_case(
                args.base_url,
                model=args.model,
                batch=batch,
                repeats=args.repeats,
                warmup=args.warmup,
                timeout=args.timeout,
                temperature=args.temperature,
                seed=args.seed,
            )
            cases.append(case)
            latency = case["latency_summary_ms"]
            throughput = case["throughput_summary_tokens_s"]
            if not args.json:
                print(
                    f"batch={batch}: "
                    f"p50={latency['p50']:.1f} ms p95={latency['p95']:.1f} ms "
                    f"mean={latency['mean']:.1f} ms | "
                    f"p50={throughput['p50']:.1f} tok/s "
                    f"mean={throughput['mean']:.1f} tok/s"
                )
                if case["response_checks"]["single_choice_for_batch"]:
                    print(
                        "  note: server generated "
                        f"{case['tokens_generated_per_request']} tokens but returned "
                        "only the first choice and reported 128 completion tokens"
                    )

        result = build_result(
            base_url=args.base_url,
            model=args.model,
            health=health,
            batches=batches,
            repeats=args.repeats,
            warmup=args.warmup,
            temperature=args.temperature,
            seed=args.seed,
            cases=cases,
        )

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if not args.json:
                print(f"\nJSON: {args.output}")

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
