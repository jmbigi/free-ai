from __future__ import annotations
from typing import Any
import json
import uuid


def repair_messages(messages: list[dict[str, Any]] | Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Best-effort OpenAI tool-call repair: dedupe tool_call ids, drop/attach orphans.
    Preserves semantics where possible; never fabricates real tool outputs.
    """
    if not isinstance(messages, list):
        return [], {'repaired': False}
    out: list[dict[str, Any]] = []
    seen_tc: set[str] = set()
    pending: dict[str, dict[str, Any]] = {}  # id -> synthetic result if missing? no, better track
    all_tc_ids: list[str] = []
    result_ids: set[str] = set()
    repairs = []

    # first pass collect assistant tool_call ids and tool result ids
    norm = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        mm = dict(m)
        tcs = mm.get('tool_calls')
        if mm.get('role') == 'assistant' and isinstance(tcs, list):
            new_tcs = []
            for tc in tcs:
                if not isinstance(tc, dict): continue
                t = dict(tc)
                tid = t.get('id') or f"call_{uuid.uuid4().hex[:12]}"
                if tid in seen_tc:
                    tid = f"{tid}_{uuid.uuid4().hex[:6]}"; repairs.append('dedupe_tool_call_id')
                seen_tc.add(tid); all_tc_ids.append(tid); t['id'] = tid
                if 'type' not in t: t['type'] = 'function'
                fn = t.get('function') if isinstance(t.get('function'), dict) else {}
                if not isinstance(fn.get('arguments',''), str):
                    try: fn['arguments'] = json.dumps(fn.get('arguments') or {}, ensure_ascii=False)
                    except Exception: fn['arguments'] = '{}'
                t['function'] = fn
                new_tcs.append(t)
            mm['tool_calls'] = new_tcs
        if mm.get('role') == 'tool' and mm.get('tool_call_id'):
            result_ids.add(str(mm['tool_call_id']))
        norm.append(mm)

    # drop orphan tool results; keep assistant/tool structure
    for mm in norm:
        if mm.get('role') == 'tool':
            tid = str(mm.get('tool_call_id') or '')
            if tid and tid not in seen_tc and tid not in all_tc_ids:
                repairs.append('drop_orphan_tool_result'); continue
        out.append(mm)

    # note missing tool results (do not fabricate content except metadata marker) — some providers tolerate; safer to not insert fake outputs
    missing = [tid for tid in all_tc_ids if tid not in result_ids]
    info = {'repaired': bool(repairs), 'repairs': repairs[:20], 'missing_tool_results': missing[:20], 'tool_calls': len(all_tc_ids), 'tool_results': len(result_ids)}
    return out, info
