"""Pure helpers for Ollama native tool-call compatibility.

Ollama's native /api/chat uses a slightly different tool format than OpenAI:
- assistant tool calls: {"function": {"name": ..., "arguments": {...}}}
- tool results: {"role": "tool", "content": ..., "tool_name": ...}
The gateway exposes OpenAI-compatible tools to clients (KimiCode, etc.), so we
must translate both directions and never discard the tool-call chain.
"""
from __future__ import annotations

import json
import uuid
from typing import Any


def text_content(value: Any) -> str:
    """Flatten OpenAI text content (str or list of content parts) to text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("output_text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        text = value.get("text") or value.get("content")
        return text if isinstance(text, str) else ""
    return str(value)


def _arguments_json(value: Any) -> str:
    """Return a JSON *string* for OpenAI function.arguments."""
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except (TypeError, ValueError):
            return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "{}"
    return json.dumps(value, ensure_ascii=False)


def _arguments_object(value: Any) -> dict[str, Any]:
    """Return a JSON object for Ollama function.arguments."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def normalize_tool_calls(raw: Any) -> list[dict[str, Any]]:
    """Normalize Ollama/OpenAI-ish tool calls to OpenAI tool_calls entries."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = fn.get("name") or item.get("name")
        if not name:
            continue
        args = fn.get("arguments", item.get("arguments", {}))
        call_id = item.get("id") or f"call_{uuid.uuid4().hex[:16]}"
        out.append(
            {
                "id": str(call_id),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": _arguments_json(args),
                },
            }
        )
    return out


def to_ollama_messages(messages: Any) -> list[dict[str, Any]]:
    """Convert OpenAI messages to Ollama native messages, preserving tools."""
    if not isinstance(messages, list):
        return []
    id_to_name: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = fn.get("name") or call.get("name")
            call_id = call.get("id")
            if call_id and name:
                id_to_name[str(call_id)] = str(name)

    out: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "developer":
            role = "system"
        converted: dict[str, Any] = {
            "role": role,
            "content": text_content(message.get("content")),
        }
        tool_calls = message.get("tool_calls")
        if role == "assistant" and isinstance(tool_calls, list):
            ollama_calls: list[dict[str, Any]] = []
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                name = fn.get("name") or call.get("name")
                if not name:
                    continue
                ollama_calls.append(
                    {
                        "function": {
                            "name": str(name),
                            "arguments": _arguments_object(
                                fn.get("arguments", call.get("arguments", {}))
                            ),
                        }
                    }
                )
            if ollama_calls:
                converted["tool_calls"] = ollama_calls
        if role == "tool":
            name = message.get("tool_name") or message.get("name")
            if not name and message.get("tool_call_id"):
                name = id_to_name.get(str(message["tool_call_id"]))
            if name:
                converted["tool_name"] = str(name)
        out.append(converted)
    return out


def build_completion(
    *,
    model: str,
    content: Any,
    thinking: Any,
    raw_tool_calls: Any,
    prompt_tokens: int,
    completion_tokens: int,
    completion_id: str,
    created: int,
    provider: str = "local-ollama",
    gateway_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an OpenAI chat.completion preserving tool calls."""
    text = text_content(content)
    reasoning = str(thinking or "")
    tool_calls = normalize_tool_calls(raw_tool_calls)
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if reasoning:
        message["reasoning"] = reasoning
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(prompt_tokens or 0) + int(completion_tokens or 0),
        },
        "provider": provider,
        "gateway": {
            "local": True,
            "ollama": True,
            "tool_calls": len(tool_calls),
            **(gateway_extra or {}),
        },
    }


def stream_delta(
    *,
    content: Any,
    thinking: Any,
    raw_tool_calls: Any,
) -> dict[str, Any]:
    """Build an OpenAI streaming delta preserving content, reasoning and tools."""
    delta: dict[str, Any] = {"role": "assistant"}
    text = text_content(content)
    reasoning = str(thinking or "")
    tool_calls = normalize_tool_calls(raw_tool_calls)
    if text:
        delta["content"] = text
    if reasoning:
        delta["reasoning"] = reasoning
    if tool_calls:
        for index, call in enumerate(tool_calls):
            call["index"] = index
        delta["tool_calls"] = tool_calls
    return delta
