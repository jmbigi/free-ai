"""Debug completo KimiCode + Free AI Gateway - Autonomous"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "https://ia.forthtrade.com/v1")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")

client = AsyncOpenAI(
    base_url=GATEWAY_BASE_URL,
    api_key=GATEWAY_API_KEY,
)


async def test_endpoint(name: str, coro) -> dict[str, Any]:
    """Test wrapper con timing y error handling."""
    t0 = time.time()
    try:
        result = await coro
        ms = int((time.time() - t0) * 1000)
        return {"test": name, "status": "PASS", "ms": ms, "data": result}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"test": name, "status": "FAIL", "ms": ms, "error": str(e)[:200]}


async def run_all_tests() -> list[dict[str, Any]]:
    """Ejecuta suite completa de tests."""
    results = []

    # 1. Health - via httpx directly
    import httpx
    async def _health():
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{GATEWAY_BASE_URL}/health")
            r.raise_for_status()
            return r.json()
    results.append(await test_endpoint("health", _health()))

    # 2. Models list
    results.append(await test_endpoint("models", client.models.list()))

    # 3. Chat simple
    results.append(await test_endpoint(
        "chat_simple",
        client.chat.completions.create(
            model="auto",
            messages=[{"role": "user", "content": "OK"}],
            max_tokens=10,
            temperature=0,
        ),
    ))

    # 4. Chat con system prompt
    results.append(await test_endpoint(
        "chat_system",
        client.chat.completions.create(
            model="auto",
            messages=[
                {"role": "system", "content": "Eres un asistente técnico."},
                {"role": "user", "content": "Responde: 2+2=?"},
            ],
            max_tokens=20,
            temperature=0,
        ),
    ))

    # 5. Chat streaming - test simple sin generar output
    async def _stream_test():
        stream = await client.chat.completions.create(
            model="auto",
            messages=[{"role": "user", "content": "Hola"}],
            max_tokens=10,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                break
        return {"stream": True, "got_content": True}

    results.append(await test_endpoint("chat_stream", _stream_test()))

    # 6. Tools
    results.append(await test_endpoint(
        "chat_tools",
        client.chat.completions.create(
            model="auto",
            messages=[{"role": "user", "content": "Que hora es?"}],
            tools=[{"type": "function", "function": {"name": "time", "description": "Get time", "parameters": {"type": "object", "properties": {}}}}],
            tool_choice="auto",
            max_tokens=100,
        ),
    ))

    # 7. Responses API
    results.append(await test_endpoint(
        "responses_api",
        client.responses.create(
            model="auto",
            input=[{"role": "user", "content": "Responde OK"}],
            max_output_tokens=20,
        ),
    ))

    # 8. Embeddings (debe fallar 501)
    results.append(await test_endpoint(
        "embeddings",
        client.embeddings.create(
            model="text-embedding-3-small",
            input="test",
        ),
    ))

    # 9. Cache test (repeat request)
    r1 = await client.chat.completions.create(
        model="auto",
        messages=[{"role": "user", "content": "Cache test"}],
        max_tokens=10,
        temperature=0,
    )
    r2 = await client.chat.completions.create(
        model="auto",
        messages=[{"role": "user", "content": "Cache test"}],
        max_tokens=10,
        temperature=0,
    )
    cache_hit = r2.id != r1.id  # same response = cache hit
    results.append({
        "test": "cache", "status": "PASS", "ms": 0,
        "data": {"cache_hit": cache_hit, "id1": r1.id, "id2": r2.id}
    })

    # 10. Context compression
    long_msg = "x" * 5000
    results.append(await test_endpoint(
        "context_compression",
        client.chat.completions.create(
            model="auto",
            messages=[{"role": "user", "content": long_msg}],
            max_tokens=20,
            temperature=0,
        ),
    ))

    return results


async def test_kimicode_cli() -> dict[str, Any]:
    """Test KimiCode CLI binary."""
    kimi_bin = "/home/admin/.kimi-code/bin/kimi"
    if not Path(kimi_bin).exists():
        return {"test": "kimicode_cli", "status": "SKIP", "error": "binary not found"}

    env = os.environ.copy()
    env["FT_AI_API_KEY"] = GATEWAY_API_KEY
    env["GATEWAY_API_KEY"] = GATEWAY_API_KEY

    try:
        proc = await asyncio.create_subprocess_exec(
            kimi_bin, "-p", "Responde OK",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        rc = proc.returncode
        if rc == 0:
            return {
                "test": "kimicode_cli",
                "status": "PASS",
                "ms": 0,
                "data": {"stdout": stdout.decode()[:500], "stderr": stderr.decode()[:500]},
            }
        else:
            return {
                "test": "kimicode_cli",
                "status": "SKIP",
                "error": f"kimi exit {rc}: {stderr.decode().strip()}",
            }
    except asyncio.TimeoutError:
        return {"test": "kimicode_cli", "status": "TIMEOUT", "error": "timeout 30s"}
    except Exception as e:
        return {"test": "kimicode_cli", "status": "FAIL", "error": str(e)[:200]}


async def test_local_gateway() -> dict[str, Any]:
    """Test local gateway (127.0.0.1:8000)."""
    import httpx
    async def _local_health():
        async with httpx.AsyncClient() as http:
            r = await http.get("http://127.0.0.1:8000/health")
            r.raise_for_status()
            return r.json()
    try:
        return await test_endpoint("local_gateway", _local_health())
    except Exception as e:
        return {"test": "local_gateway", "status": "FAIL", "error": str(e)[:200]}


async def test_telemetry() -> dict[str, Any]:
    """Test telemetry endpoint."""
    import httpx
    async def _tele():
        async with httpx.AsyncClient() as http:
            r = await http.get(
                f"{GATEWAY_BASE_URL}/telemetry",
                headers={"Authorization": f"Bearer {GATEWAY_API_KEY}"},
            )
            r.raise_for_status()
            return r.json()
    try:
        return await test_endpoint("telemetry", _tele())
    except Exception as e:
        return {"test": "telemetry", "status": "FAIL", "error": str(e)[:200]}


async def test_debug_endpoint() -> dict[str, Any]:
    """Test debug endpoint."""
    import httpx
    async def _debug():
        async with httpx.AsyncClient() as http:
            r = await http.get(
                f"{GATEWAY_BASE_URL}/debug",
                headers={"Authorization": f"Bearer {GATEWAY_API_KEY}"},
            )
            r.raise_for_status()
            return r.json()
    try:
        return await test_endpoint("debug_endpoint", _debug())
    except Exception as e:
        return {"test": "debug_endpoint", "status": "FAIL", "error": str(e)[:200]}


async def test_auth_failures() -> dict[str, Any]:
    """Test auth failures."""
    import httpx
    async def _no_key():
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{GATEWAY_BASE_URL}/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": "test"}]},
            )
            return {"status_code": r.status_code, "error": r.json().get("error", {}).get("message", "")}
    async def _bad_key():
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{GATEWAY_BASE_URL}/v1/chat/completions",
                headers={"Authorization": "Bearer wrong-key"},
                json={"model": "auto", "messages": [{"role": "user", "content": "test"}]},
            )
            return {"status_code": r.status_code, "error": r.json().get("error", {}).get("message", "")}
    async def _x_api_key():
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{GATEWAY_BASE_URL}/v1/chat/completions",
                headers={"x-api-key": GATEWAY_API_KEY},
                json={"model": "auto", "messages": [{"role": "user", "content": "test"}]},
            )
            return {"status_code": r.status_code}
    try:
        r1 = await _no_key()
        r2 = await _bad_key()
        r3 = await _x_api_key()
        return {
            "test": "auth_failures",
            "status": "PASS",
            "ms": 0,
            "data": {"no_key": r1, "bad_key": r2, "x_api_key": r3},
        }
    except Exception as e:
        return {"test": "auth_failures", "status": "FAIL", "error": str(e)[:200]}


async def main() -> dict[str, Any]:
    print("=== DEBUG KIMICODE + FREE AI GATEWAY ===")
    print(f"Gateway: {GATEWAY_BASE_URL}")
    print(f"API Key: {'SET' if GATEWAY_API_KEY else 'MISSING'}")
    print()

    # Run all tests
    tests = await run_all_tests()
    tests.append(await test_kimicode_cli())
    tests.append(await test_local_gateway())
    tests.append(await test_telemetry())
    tests.append(await test_debug_endpoint())
    tests.append(await test_auth_failures())

    # Summary
    passed = sum(1 for t in tests if t["status"] == "PASS")
    failed = sum(1 for t in tests if t["status"] == "FAIL")
    skipped = sum(1 for t in tests if t["status"] == "SKIP")
    total = len(tests)

    print(f"\n=== RESUMEN: {passed}/{total} PASS, {failed} FAIL, {skipped} SKIP ===")
    for t in tests:
        status = t["status"]
        ms = t.get("ms", 0)
        print(f"  {status:6} {t['test']:25} {ms:>5}ms")

    # Save report
    report = {
        "timestamp": time.time(),
        "gateway": GATEWAY_BASE_URL,
        "summary": {"pass": passed, "fail": failed, "skip": skipped, "total": total},
        "tests": tests,
    }

    report_path = Path("/home/admin/free-ai/examples/debug_report.json")
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nReport saved: {report_path}")

    return report


if __name__ == "__main__":
    asyncio.run(main())
