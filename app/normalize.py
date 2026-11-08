from __future__ import annotations
from typing import Any

_REASONING_KEYS = ('reasoning', 'reasoning_content', 'thinking', 'thought')


def _extract_text(content: Any) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for x in content:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                t = x.get('text') or x.get('output_text') or x.get('content')
                if isinstance(t, str):
                    parts.append(t)
        return '\n'.join(p for p in parts if p)
    if isinstance(content, dict):
        t = content.get('text') or content.get('content')
        return t if isinstance(t, str) else ''
    return ''


def normalize_chat_response(data: dict[str, Any] | Any) -> Any:
    """Make upstream chat responses more compatible with OpenAI clients/gateway code.
    - Promotes reasoning-only output to content when content is empty and no tool calls.
    - Normalizes list content to text where safe.
    Never fabricates content when a real answer/tool call exists.
    """
    if not isinstance(data, dict):
        return data
    choices = data.get('choices')
    if not isinstance(choices, list):
        return data
    for ch in choices:
        if not isinstance(ch, dict):
            continue
        msg = ch.get('message') if isinstance(ch.get('message'), dict) else (ch.get('delta') if isinstance(ch.get('delta'), dict) else None)
        if not isinstance(msg, dict):
            continue
        text = _extract_text(msg.get('content'))
        if not text and not msg.get('tool_calls') and not msg.get('function_call'):
            for k in _REASONING_KEYS:
                v = msg.get(k)
                if isinstance(v, str) and v.strip():
                    # keep reasoning field, but also provide content for compatibility
                    msg['content'] = v.strip()
                    data.setdefault('gateway', {})
                    if isinstance(data['gateway'], dict):
                        data['gateway']['content_from_reasoning'] = True
                    break
                if isinstance(v, list):
                    joined = '\n'.join(str(x.get('text') or x) for x in v if x)
                    if joined.strip():
                        msg['content'] = joined.strip()
                        data.setdefault('gateway', {})
                        if isinstance(data['gateway'], dict):
                            data['gateway']['content_from_reasoning'] = True
                        break
        elif text and not isinstance(msg.get('content'), str):
            msg['content'] = text
    return data
