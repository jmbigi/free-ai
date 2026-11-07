from __future__ import annotations
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
    # remove very long repeated whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if aggressive:
        # compact common log/code noise while preserving meaning
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
            # shorten very long lines
            if len(l) > 500:
                l = l[:260] + " … " + l[-180:]
            lines.append(l)
        if repeats > 1 and lines:
            lines[-1] = f"{lines[-1]} […repetido {repeats}x…]"
        text = "\n".join(lines)
    return text.strip()


def estimate_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(_s(m.get("content"))) + len(str(m.get("role", ""))) for m in messages if isinstance(m, dict))


def compress_messages(payload: dict[str, Any]) -> dict[str, Any]:
    if not bool(getattr(settings, 'context_compress_enabled', True)):
        return payload
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

    force = bool(payload.get("compress_context") is True or gw.get("compress_context") is True)
    total = estimate_chars(messages)
    if not force and total <= max_chars:
        # still compact pathological single messages
        changed = False
        out = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            mm = dict(m)
            c = _s(mm.get("content"))
            if len(c) > msg_max * 2:
                mm["content"] = _clip(_compress_text(c), msg_max)
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

    summary_bits = []
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
    summary = _clip(summary, summary_max) if summary else "(sin historial previo relevante)"

    out = []
    # keep system messages compact
    for m in system_like[-3:]:
        mm = dict(m)
        mm["content"] = _clip(_compress_text(_s(mm.get("content"))), msg_max)
        out.append(mm)
    out.append({
        "role": "system",
        "content": "[Contexto comprimido por Free AI Gateway para caber en proveedores remotos/caché]\nResumen de mensajes anteriores:\n" + summary,
    })
    for m in recent:
        mm = dict(m)
        mm["content"] = _clip(_compress_text(_s(mm.get("content"))), msg_max)
        out.append(mm)

    # final guard
    if estimate_chars(out) > max_chars:
        # trim recent from the front except last 2
        fixed = out[: 1 + min(1, len(system_like))]
        tail = out[1 + min(1, len(system_like)) :]
        while estimate_chars(fixed + tail) > max_chars and len(tail) > 3:
            tail.pop(1)  # after summary
        out = fixed + tail

    payload = dict(payload)
    payload["messages"] = out
    payload.setdefault("gateway", {})
    payload["gateway"].update({
        "context_compressed": True,
        "context_chars_before": total,
        "context_chars_after": estimate_chars(out),
        "messages_before": len(messages),
        "messages_after": len(out),
        "mode": "history-summary+trim",
    })
    return payload
