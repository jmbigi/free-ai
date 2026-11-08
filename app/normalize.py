from __future__ import annotations
from typing import Any


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
    - Preserves reasoning/thinking as separate entries when present.
    - Normalizes list content to text where safe.
    Never fabricates content when a real answer/tool call exists.
    Never silently drops reasoning fields into content (keeps them distinct for clients like KimiCode that expect separate reasoning UI).
    When content is None/empty AND finish_reason is 'length', raise a clear error so
    clients don't receive null content and confuse them with 'empty response'.
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
        finish = ch.get('finish_reason') or (ch.get('native_finish_reason') if isinstance(ch.get('native_finish_reason'), str) else None)
        # If content is empty but finish is "length" (token budget exhausted), raise to avoid null content confusion.
        if not text and not msg.get('tool_calls') and not msg.get('function_call') and str(finish).lower() == 'length':
            raise ValueError("Provider returned only reasoning content with finish_reason='length'; output token budget exhausted.")
        if not text and not msg.get('tool_calls') and not msg.get('function_call'):
            # Preserve reasoning/thinking as distinct fields; do NOT merge into content.
            # Remove marker if previously set, to keep reasoning distinct.
            if 'content_from_reasoning' in msg or (isinstance(data.get('gateway'), dict) and data['gateway'].get('content_from_reasoning')):
                # clean up any previously-promoted marker so reasoning stays distinct
                if isinstance(data.get('gateway'), dict):
                    data['gateway'].pop('content_from_reasoning', None)
            # Keep reasoning/thinking fields exactly as-is; do not reassign to content.
            # Only move content if there is actual text content already present.
        elif text and not isinstance(msg.get('content'), str):
            msg['content'] = text
    return data