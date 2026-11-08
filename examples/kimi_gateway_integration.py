"""Free AI Gateway + Kimi Integration Example - Advanced"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from openai import AsyncOpenAI

GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "https://ia.forthtrade.com/v1")
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")

client = AsyncOpenAI(
    base_url=GATEWAY_BASE_URL,
    api_key=GATEWAY_API_KEY,
)


async def test_kimi_gateway_simple() -> dict[str, Any]:
    """Test con modelo auto."""
    resp = await client.chat.completions.create(
        model="auto",
        messages=[
            {"role": "system", "content": "Eres un asistente útil."},
            {"role": "user", "content": "Hola, responde OK"},
        ],
        max_tokens=30,
        temperature=0.0,
    )
    return {
        "model": resp.model,
        "content": resp.choices[0].message.content,
        "usage": resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage),
    }


async def test_kimi_gateway_tools() -> dict[str, Any]:
    """Test con tools (KimiCode style)."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "description": "Get current time",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    resp = await client.chat.completions.create(
        model="auto",
        messages=[
            {"role": "system", "content": "Eres un asistente útil."},
            {"role": "user", "content": "Cual es la hora?"},
        ],
        tools=tools,
        tool_choice="auto",
        max_tokens=200,
    )
    return {
        "message": resp.choices[0].message.model_dump(),
        "usage": resp.usage.model_dump() if hasattr(resp.usage, "model_dump") else dict(resp.usage),
    }


async def test_kimi_gateway_responses() -> dict[str, Any]:
    """Test con /responses endpoint (KimiCode compatible)."""
    resp = await client.responses.create(
        model="auto",
        input=[
            {"role": "user", "content": "Responde OK"},
        ],
        max_output_tokens=30,
    )
    return {"id": resp.id, "output": resp.output}


async def main() -> None:
    print("[Kimi+Gateway] Test simple...")
    r1 = await test_kimi_gateway_simple()
    print(json.dumps(r1, indent=2, default=str))

    print("[Kimi+Gateway] Test tools...")
    r2 = await test_kimi_gateway_tools()
    print(json.dumps(r2, indent=2, default=str))

    print("[Kimi+Gateway] Test responses...")
    r3 = await test_kimi_gateway_responses()
    print(json.dumps(r3, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
