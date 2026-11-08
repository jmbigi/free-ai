from __future__ import annotations
import json
import re
import uuid
from typing import Any

from .logging import log as _log

TOOL_SYSTEM = (
    "Gateway compatibility layer: if you need to call a tool/function, respond with ONLY a JSON object: "
    "{\"tool_calls\":[{\"id\":\"call_x\",\"type\":\"function\",\"function\":{\"name\":\"NAME\",\"arguments\":\"{...json...}\"}}]} . "
    "No markdown. If no tool is needed, answer normally."
)


def has_tools(payload: dict[str, Any]) -> bool:
    return bool(payload.get('tools') or payload.get('functions') or payload.get('tool_choice') in ('required',) or (isinstance(payload.get('tool_choice'), dict)))


def inject_tool_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    if not has_tools(payload):
        return payload
    p = dict(payload)
    msgs = list(p.get('messages') or [])
    spec = {'tools': p.get('tools'), 'tool_choice': p.get('tool_choice', 'auto')}
    text = TOOL_SYSTEM + "\nAvailable tool spec (JSON): " + json.dumps(spec, ensure_ascii=False)[:12000]
    # prepend as system without destroying existing system/developer
    if msgs and isinstance(msgs[0], dict) and msgs[0].get('role') in ('system', 'developer'):
        m0 = dict(msgs[0])
        c = m0.get('content')
        m0['content'] = (str(c) + "\n\n" + text) if c else text
        msgs[0] = m0
    else:
        msgs.insert(0, {'role': 'system', 'content': text})
    p['messages'] = msgs
    # keep tools/tool_choice too; upstream may support them
    return p


def _parse_json_candidate(s: str) -> Any:
    s = (s or '').strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        _log.debug("tool-call JSON parse failed, trying embedded object: %s", e)
    # fenced or embedded object
    m = re.search(r'\{[\s\S]*\}', s)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def maybe_synthesize_tool_calls(data: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not has_tools(payload) or not isinstance(data, dict):
        return data
    choices = data.get('choices')
    if not isinstance(choices, list) or not choices:
        return data
    msg = choices[0].get('message') if isinstance(choices[0], dict) else None
    if not isinstance(msg, dict):
        return data
    if msg.get('tool_calls') or msg.get('function_call'):
        return data
    content = msg.get('content')
    if not isinstance(content, str):
        return data
    obj = _parse_json_candidate(content)
    if not isinstance(obj, dict):
        return data
    tcs = obj.get('tool_calls')
    if not isinstance(tcs, list) or not tcs:
        # allow {"name":...,"arguments":...}
        if obj.get('name') and ('arguments' in obj):
            tcs = [{'type':'function','function':{'name':obj['name'],'arguments':obj.get('arguments')}}]
        else:
            return data
    norm = []
    for i, tc in enumerate(tcs):
        if not isinstance(tc, dict):
            continue
        fn = tc.get('function') if isinstance(tc.get('function'), dict) else {}
        name = fn.get('name') or tc.get('name')
        args = fn.get('arguments') if 'arguments' in fn else tc.get('arguments')
        if name is None:
            continue
        if not isinstance(args, str):
            try:
                args = json.dumps(args if args is not None else {}, ensure_ascii=False)
            except Exception:
                args = '{}'
        norm.append({'id': tc.get('id') or f"call_{uuid.uuid4().hex[:16]}", 'type': 'function', 'function': {'name': name, 'arguments': args}})
    if not norm:
        return data
    msg['tool_calls'] = norm
    msg['content'] = None
    choices[0]['finish_reason'] = 'tool_calls'
    data.setdefault('gateway', {})['tool_calls_synthesized'] = True
    return data
