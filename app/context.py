from __future__ import annotations
import json
import re
from typing import Any

from .config import settings

_WS = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


def _s(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, dict):
                if x.get("type") == "text":
                    parts.append(str(x.get("text", "")))
                elif "text" in x:
                    parts.append(str(x.get("text", "")))
                elif "input_text" in x:
                    parts.append(str(x.get("input_text", "")))
                else:
                    parts.append(f"[{x.get('type','part')}]")
            else:
                parts.append(str(x))
        return "\n".join(p for p in parts if p)
    return str(v)


def _clip(text: str, max_chars: int) -> str:
    text = _WS.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = _BLANKS.sub("\n\n", text).strip()
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head - 40
    if tail < 80:
        return text[: max_chars - 20] + "\n[…truncado…]"
    return text[:head].rstrip() + "\n[…contexto comprimido/truncado…]\n" + text[-tail:].lstrip()


def _compress_text(text: str, aggressive: bool = False) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if aggressive:
        lines = []
        prev = None
        repeats = 0
        for line in text.splitlines():
            l = line.rstrip()
            if l == prev:
                repeats += 1
                if repeats <= 1:
                    lines.append(l)
                continue
            if repeats > 1:
                lines[-1] = f"{lines[-1]} […repetido {repeats}x…]"
            repeats = 0
            prev = l
            if len(l) > 500:
                l = l[:260] + " … " + l[-180:]
            lines.append(l)
        if repeats > 1 and lines:
            lines[-1] = f"{lines[-1]} […repetido {repeats}x…]"
        text = "\n".join(lines)
    return text.strip()


def estimate_chars(messages: list[dict[str, Any]]) -> int:
    t = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        t += len(_s(m.get("content"))) + len(str(m.get("role", "")))
        if m.get("tool_calls"):
            try:
                t += len(json.dumps(m["tool_calls"], ensure_ascii=False))
            except Exception:
                t += 200
        if m.get("tool_call_id"):
            t += len(str(m["tool_call_id"]))
    return t


def _has_tools(payload: dict[str, Any], messages: list[dict[str, Any]]) -> bool:
    if payload.get("tools") or payload.get("functions") or payload.get("tool_choice") or payload.get("function_call"):
        return True
    for m in messages:
        if isinstance(m, dict) and (m.get("role") == "tool" or m.get("tool_calls") or m.get("tool_call_id") or m.get("function_call")):
            return True
    return False


def _compact_content(c: Any, msg_max: int) -> Any:
    # Preserve structured/multimodal content where reasonable; only compact large text parts.
    if c is None or not isinstance(c, list):
        s = _s(c)
        return _clip(_compress_text(s), msg_max) if len(s) > msg_max else (_compress_text(s) if s else c)
    out = []
    for part in c:
        if isinstance(part, dict) and part.get("type") in ("text", "input_text") and isinstance(part.get("text") or part.get("input_text"), str):
            pp = dict(part)
            key = "text" if "text" in pp else "input_text"
            txt = _compress_text(pp[key])
            if len(txt) > msg_max // 2:
                txt = _clip(txt, msg_max // 2)
            pp[key] = txt
            out.append(pp)
        else:
            out.append(part)
    return out


def _preserve_message(m: dict[str, Any], msg_max: int, compress_text: bool = True) -> dict[str, Any]:
    mm = dict(m)
    # Never destroy tool/function calling structure.
    if compress_text and "content" in mm and mm.get("content") is not None:
        c = mm["content"]
        if isinstance(c, str):
            if len(c) > msg_max:
                mm["content"] = _clip(_compress_text(c), msg_max)
            else:
                mm["content"] = _compress_text(c)
        elif isinstance(c, list):
            mm["content"] = _compact_content(c, msg_max)
    # assistant tool_calls must remain intact
    # tool message fields tool_call_id/name must remain intact
    return mm


def compress_messages(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(getattr(settings, 'context_compress_enabled', True)):
        return payload
    if not isinstance(payload.get("gateway"), dict):
        payload = dict(payload)
        payload.pop("gateway", None)
    gw = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
    if payload.get("compress_context") is False or gw.get("compress_context") is False:
        return payload
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return payload

    max_chars = int(getattr(settings, 'context_max_chars', 120000) or 120000)
    keep_last = int(getattr(settings, 'context_keep_last_messages', 12) or 12)
    msg_max = int(getattr(settings, 'context_message_max_chars', 12000) or 12000)
    summary_max = int(getattr(settings, 'context_summary_max_chars', 4000) or 4000)
    tool_mode = _has_tools(payload, messages)

    force = bool(payload.get("compress_context") is True or gw.get("compress_context") is True)
    total = estimate_chars(messages)
    if not force and total <= max_chars:
        changed = False
        out = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            mm = _preserve_message(m, msg_max)
            if mm != m:
                changed = True
            out.append(mm)
        if changed:
            payload = dict(payload)
            payload["messages"] = out
            payload.setdefault("gateway", {})
            payload["gateway"].update({"context_compressed": True, "context_chars_before": total, "context_chars_after": estimate_chars(out), "mode": "single-message-trim"})
        return payload

    system_like = [m for m in messages if isinstance(m, dict) and m.get("role") in ("system", "developer")]
    rest = [m for m in messages if isinstance(m, dict) and m.get("role") not in ("system", "developer")]
    if len(rest) <= max(4, keep_last):
        keep_last = max(2, len(rest) // 2)
    old = rest[:-keep_last] if keep_last > 0 else rest
    recent = rest[-keep_last:] if keep_last > 0 else []

    # In tool mode, avoid summarizing away messages that may break tool_call_id chains.
    # Keep recent intact and only trim/compact old text; if still large, drop oldest old messages.
    summary_bits = []
    if not tool_mode:
        for m in old[-40:]:
            role = str(m.get("role", "msg"))
            text = _compress_text(_s(m.get("content")), aggressive=True)
            if not text:
                continue
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 220:
                text = text[:160].rstrip() + " … " + text[-50:].lstrip()
            summary_bits.append(f"- {role}: {text}")
    summary = "\n".join(summary_bits)
    summary = _clip(summary, summary_max) if summary else ""

    out = []
    for m in system_like[-3:]:
        out.append(_preserve_message(dict(m), msg_max))
    if summary and not tool_mode:
        out.append({"role": "system", "content": "[Contexto comprimido por Free AI Gateway]\nResumen de mensajes anteriores:\n" + summary})
    elif tool_mode and old:
        # keep compacted old messages (preserve structure), newest-old first drop if needed
        for m in old[-20:]:
            out.append(_preserve_message(dict(m), max(800, msg_max // 2), compress_text=True))
    for m in recent:
        out.append(_preserve_message(dict(m), msg_max, compress_text=(m.get('role') not in ('tool',))))

    # final guard
    def _total():
        return estimate_chars(out)
    if _total() > max_chars:
        # remove old compacted/tool-context messages from front of that section, keep system+last 2
        while _total() > max_chars and len(out) > max(3, len(system_like) + 2):
            # drop after system messages
            drop_at = min(len(system_like), len(out) - 2)
            if drop_at >= len(out) - 2:
                break
            out.pop(drop_at)
    if _total() > max_chars and len(out) >= 2:
        # last resort: clip large content fields except tool call structure
        for mm in out:
            if isinstance(mm, dict) and isinstance(mm.get('content'), str) and len(mm['content']) > 1200 and mm.get('role') != 'tool':
                mm['content'] = _clip(mm['content'], 1200)
            if _total() <= max_chars:
                break

    payload = dict(payload)
    payload["messages"] = out
    payload.setdefault("gateway", {})
    payload["gateway"].update({
        "context_compressed": True,
        "context_chars_before": total,
        "context_chars_after": estimate_chars(out),
        "messages_before": len(messages),
        "messages_after": len(out),
        "mode": "tool-safe-trim" if tool_mode else "history-summary+trim",
    })
    return payload
