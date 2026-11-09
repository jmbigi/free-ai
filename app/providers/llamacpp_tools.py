"""Tool-call compatibility helpers for llama-cpp-python / Qwen3-Coder.

llama-cpp-python's OpenAI-compatible server renders the GGUF chat template but
does not always turn the model's XML tool-call text into OpenAI ``tool_calls``.
Qwen3-Coder emits:

    <tool_call>
    <function=write_file>
    <parameter=path>
    x.txt
    </parameter>
    <parameter=content>
    ok
    </parameter>
    </function>
    </tool_call>

The gateway must expose those calls as OpenAI ``tool_calls`` so agent clients
(KimiCode, OpenCode, etc.) can execute them and send the result back.  The
reverse direction is also needed: llama.cpp's template expects
``function.arguments`` as a mapping while OpenAI clients send a JSON string.
"""
from __future__ import annotations

import copy
import json
import re
import uuid
from typing import Any

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.IGNORECASE | re.DOTALL)
_FUNCTION_XML_RE = re.compile(r"<function(?:\s+name=\"([^\"]+)\"|=([^>\s]+))>\s*(.*?)\s*</function>", re.IGNORECASE | re.DOTALL)
_PARAM_XML_RE = re.compile(r"<parameter(?:\s+name=\"([^\"]+)\"|=([^>\s]+))>\s*(.*?)\s*</parameter>", re.IGNORECASE | re.DOTALL)


def _scalar(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _arguments_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _call(name: str, arguments: Any, call_id: str | None = None) -> dict[str, Any]:
    return {
        "id": call_id or f"call_{uuid.uuid4().hex[:16]}",
        "type": "function",
        "function": {
            "name": str(name),
            "arguments": json.dumps(_arguments_object(arguments), ensure_ascii=False),
        },
    }


def _parse_xml_block(block: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fn_match in _FUNCTION_XML_RE.finditer(block):
        name = (fn_match.group(1) or fn_match.group(2) or "").strip()
        if not name:
            continue
        args: dict[str, Any] = {}
        for param_match in _PARAM_XML_RE.finditer(fn_match.group(3)):
            key = (param_match.group(1) or param_match.group(2) or "").strip()
            if key:
                args[key] = _scalar(param_match.group(3))
        out.append(_call(name, args))
    return out


def _parse_json_block(block: str) -> list[dict[str, Any]]:
    text = block.strip()
    # Some templates wrap the JSON in a code fence or a python tag.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return []
    items = obj if isinstance(obj, list) else [obj]
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        args = item.get("arguments", item.get("parameters", {}))
        if not name and isinstance(item.get("function"), dict):
            fn = item["function"]
            name = fn.get("name")
            args = fn.get("arguments", fn.get("parameters", {}))
        if name:
            out.append(_call(str(name), args))
    return out


def extract_content_tool_calls(content: Any, *, allow_bare_json: bool = False) -> tuple[str, list[dict[str, Any]]]:
    """Return (clean_text, OpenAI tool_calls) parsed from model content."""
    if not isinstance(content, str) or not content:
        return "", []
    calls: list[dict[str, Any]] = []
    blocks = list(_TOOL_CALL_RE.finditer(content))
    for match in blocks:
        block = match.group(1)
        parsed = _parse_xml_block(block) or _parse_json_block(block)
        calls.extend(parsed)
    clean = _TOOL_CALL_RE.sub("", content).strip()

    if not calls and allow_bare_json:
        # Some llama.cpp templates omit the <tool_call> wrapper.  Only accept a
        # bare object that has an explicit name/arguments shape so ordinary JSON
        # answers are not misclassified as tool calls.
        parsed = _parse_json_block(clean)
        if parsed:
            calls.extend(parsed)
            clean = ""

    return clean, calls


def _format_parameter(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)


def tool_calls_to_qwen_xml(tool_calls: Any) -> str:
    """Serialize OpenAI tool_calls as the Qwen3-Coder XML the GGUF sees."""
    if not isinstance(tool_calls, list):
        return ""
    parts: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = fn.get("name") or call.get("name")
        if not name:
            continue
        args = _arguments_object(fn.get("arguments", call.get("arguments", {})))
        parts.append("<tool_call>\n")
        parts.append(f"<function={name}>\n")
        for key, value in args.items():
            parts.append(f"<parameter={key}>\n{_format_parameter(value)}\n</parameter>\n")
        parts.append("</function>\n</tool_call>")
    return "\n".join(parts)


def to_llamacpp_messages(messages: Any) -> list[dict[str, Any]]:
    """Convert OpenAI tool messages to the shape the GGUF Qwen template accepts.

    llama-cpp-python's FastAPI request model validates assistant ``tool_calls``
    as OpenAI strings, while its GGUF template expects mapping arguments.  The
    safest wire format is to serialize assistant calls into the Qwen XML inside
    the assistant content and let the template render tool results normally.
    This preserves the exact history without relying on a broken validator.
    """
    if not isinstance(messages, list):
        return []
    out: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        item = copy.deepcopy(message)
        if item.get("role") == "assistant" and isinstance(item.get("tool_calls"), list):
            xml = tool_calls_to_qwen_xml(item.get("tool_calls"))
            content = item.get("content")
            content = content if isinstance(content, str) else ("" if content is None else str(content))
            item["content"] = (content + "\n" if content.strip() else "") + xml
            item.pop("tool_calls", None)
        if item.get("role") == "tool" and not item.get("tool_call_id"):
            # The FastAPI model requires tool_call_id; fall back to a user
            # message so a malformed client does not get a hard 400.
            item = {
                "role": "user",
                "content": f"Tool result:\n{item.get('content') or ''}",
            }
        # llama.cpp's template also accepts `name`; tool_call_id is useful for
        # OpenAI clients and is ignored by the template.
        out.append(item)
    return out


def openai_tool_calls(raw: Any) -> list[dict[str, Any]]:
    """Normalize dict/list tool calls while preserving ids and JSON arguments."""
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
        out.append(_call(str(name), fn.get("arguments", item.get("arguments", {})), item.get("id")))
    return out
