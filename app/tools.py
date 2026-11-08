from __future__ import annotations
import inspect
import json
import re
from pathlib import Path
from typing import Any, AsyncIterator

from .logging import log as _log
from .observability import metrics as _metrics


STANDARD_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns content or error.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path relative to working dir or absolute allowed"}}, "required": ["path"]},
    },
    {
        "name": "write_file",
        "description": "Write text content to a file. Creates parent dirs if needed.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path relative to working dir or absolute allowed"}}, "required": ["path", "content"]},
    },
    {
        "name": "edit_file",
        "description": "Edit a file by replacing exact string. Requires old_str present.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "File path"}}, "required": ["path", "old_str", "new_str"]},
    },
    {
        "name": "list_dir",
        "description": "List directory contents (files and subdirs) with sizes.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Directory path (default: '.')"}}, "required": ["path"]},
    },
    {
        "name": "run_bash",
        "description": "Execute a bash command with timeout. Max 120 chars output.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "Bash command to run"}}, "required": ["command"]},
    },
    {
        "name": "grep",
        "description": "Search for a regex pattern in files under a path.",
        "parameters": {"type": "object", "properties": {"pattern": {"type": "string", "description": "Regex pattern"}}, "required": ["pattern"]},
    },
    {
        "name": "web_search",
        "description": "Search the web via free providers. Returns results or error.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}}, "required": ["query"]},
    },
    {
        "name": "web_fetch",
        "description": "Fetch a URL and return cleaned text/markdown. Max 30k chars.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "URL to fetch"}}, "required": ["url"]},
    },
    {
        "name": "python_exec",
        "description": "Execute Python code in a sandboxed-ish subprocess. Returns stdout/err.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string", "description": "Python code to run"}}, "required": ["code"]},
    },
    {
        "name": "json_query",
        "description": "Query JSON data with jq-like syntax (keys/paths).",
        "parameters": {"type": "object", "properties": {"data": {"type": "string", "description": "JSON string"}}, "required": ["data"]},
    },
]


def build_standard_tools() -> list[dict[str, Any]]:
    """Build OpenAI-compatible tool definitions for all standard tools."""
    return [{"type": "function", "function": t} for t in STANDARD_TOOLS]


def inject_tools_system_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject system prompt with all available tools."""
    if not payload.get("tools") and not payload.get("tool_choice") and not payload.get("functions"):
        return payload
    p = dict(payload)
    msgs = list(p.get("messages") or [])
    spec = {"tools": p.get("tools"), "tool_choice": p.get("tool_choice", "auto")}
    text = (
        "You have access to the following tools. When you need to use a tool, "
        "respond with ONLY a JSON object in this format:\n"
        '{"tool_calls":[{"id":"call_x","type":"function","function":{"name":"TOOL_NAME","arguments":"{...json...}"}}]}\n'
        "No markdown. If no tool is needed, answer normally.\n\n"
        "Available tools (JSON): " + json.dumps(spec, ensure_ascii=False)[:15000]
    )
    if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") in ("system", "developer"):
        m0 = dict(msgs[0])
        c = m0.get("content")
        m0["content"] = (str(c) + "\n\n" + text) if c else text
        msgs[0] = m0
    else:
        msgs.insert(0, {"role": "system", "content": text})
    p["messages"] = msgs
    return p


def _safe_path(path: str, *, must_exist: bool = False, is_dir: bool = False) -> Path | None:
    """Resolve path safely. Reject traversal outside allowed root."""
    if not isinstance(path, str) or not path.strip():
        return None
    p = Path(path.strip())
    if not path.strip():
        return None
    try:
        resolved = p.resolve()
    except Exception:
        return None
    if not is_dir and must_exist:
        if not resolved.exists():
            return None
    if resolved.is_relative_to(Path("/tmp")) or resolved.is_relative_to(Path("/home")):
        return resolved
    return None


def _read_file(args: dict[str, Any]) -> dict[str, Any]:
    path = _safe_path(str(args.get("path") or ""))
    if not path:
        return {"status": "error", "error": "invalid or unsafe path", "path": str(args.get("path"))}
    if not path.is_file():
        return {"status": "error", "error": f"file not found: {path}"}
    content = path.read_text(encoding="utf-8", errors="replace")[:30000]
    return {"status": "ok", "path": str(path), "content": content}


def _write_file(args: dict[str, Any]) -> dict[str, Any]:
    path = _safe_path(str(args.get("path") or ""))
    content = str(args.get("content") or "")
    if not path:
        return {"status": "error", "error": "invalid or unsafe path", "path": str(args.get("path"))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"status": "ok", "path": str(path), "bytes_written": len(content.encode("utf-8"))}


def _edit_file(args: dict[str, Any]) -> dict[str, Any]:
    path = _safe_path(str(args.get("path") or ""), must_exist=True)
    old_str = str(args.get("old_str") or "")
    new_str = str(args.get("new_str") or "")
    if not path or not path.is_file():
        return {"status": "error", "error": "file not found", "path": str(args.get("path"))}
    text = path.read_text(encoding="utf-8", errors="replace")
    if old_str not in text:
        return {"status": "error", "error": "old_str not found in file", "path": str(path)}
    path.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
    return {"status": "ok", "path": str(path)}


def _list_dir(args: dict[str, Any]) -> dict[str, Any]:
    path = _safe_path(str(args.get("path") or "") or ".", is_dir=True) or Path("/tmp")
    if not path.is_dir():
        return {"status": "error", "error": f"not a directory: {path}"}
    out = []
    for p in sorted(path.iterdir())[:200]:
        try:
            out.append({"name": p.name, "type": "dir" if p.is_dir() else "file", "size": p.stat().st_size if p.is_file() else 0})
        except Exception as e:
            return {"status": "error", "error": str(e)}
    return {"status": "ok", "path": str(path), "entries": out}


def _run_bash(args: dict[str, Any]) -> dict[str, Any]:
    import subprocess
    cmd = str(args.get("command") or "")
    if not cmd.strip():
        return {"status": "error", "error": "empty command"}
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, cwd="/tmp")
        out = (r.stdout or "")[:12000]
        err = (r.stderr or "")[:4000]
        return {"status": "ok", "returncode": r.returncode, "stdout": out, "stderr": err}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _grep(args: dict[str, Any]) -> dict[str, Any]:
    path = _safe_path(str(args.get("path") or "/tmp") or "/tmp", is_dir=True) or Path("/tmp")
    pattern = re.compile(str(args.get("pattern") or ".*"))
    hits = []
    for p in path.rglob("*"):
        if p.is_file():
            try:
                if len(list(pattern.finditer(p.read_text(encoding="utf-8", errors="replace")))) > 0:
                    hits.append(str(p))
            except Exception:
                pass
    return {"status": "ok", "path": str(path), "count": len(hits), "files": hits[:50]}


async def _web_search(args: dict[str, Any]) -> dict[str, Any]:
    from .search import web_search
    res = await web_search(str(args.get("query") or ""))
    return {"status": "ok", "object": res.get("object"), "provider": res.get("provider"), "count": len(res.get("results") or []), "error": res.get("error") or None, "results": res.get("results") or []}


def _web_fetch(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "")
    try:
        import httpx
        from .search import _cache_get, _cache_set
        cached = _cache_get("web_fetch|" + url, ttl=60)
        if cached:
            return {"status": "ok", "cached": True, **cached}
        with httpx.Client(timeout=15, follow_redirects=True) as c:
            r = c.get(url, headers={"User-Agent": "FreeAIGateway/2.2"})
            text = r.text[:30000]
        out = {"status": "ok", "url": url, "content": text, "final_url": str(r.url)}
        _cache_set("web_fetch|" + url, out)
        return out
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _python_exec(args: dict[str, Any]) -> dict[str, Any]:
    code = str(args.get("code") or "")
    try:
        import subprocess, json as _json
        r = subprocess.run(["python", "-c", code], capture_output=True, text=True, timeout=30, cwd="/tmp")
        return {"status": "ok", "returncode": r.returncode, "stdout": (r.stdout or "")[:12000], "stderr": (r.stderr or "")[:4000]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _json_query(args: dict[str, Any]) -> dict[str, Any]:
    data_str = str(args.get("data") or "")
    try:
        data = json.loads(data_str)
        path = str(args.get("path") or "")
        val: Any = data
        if path:
            for part in [p for p in path.split(".") if p.strip()]:
                val = val.get(part) if isinstance(val, dict) else None
        return {"status": "ok", "data": val}
    except Exception as e:
        return {"status": "error", "error": f"json error: {e}"}


_TOOL_IMPL = {
    "read_file": _read_file,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "list_dir": _list_dir,
    "run_bash": _run_bash,
    "grep": _grep,
    "web_search": _web_search,
    "web_fetch": _web_fetch,
    "python_exec": _python_exec,
    "json_query": _json_query,
}


def get_all_tool_definitions() -> list[dict[str, Any]]:
    """Get complete list of all standard tool definitions for /v1/tools endpoint."""
    return STANDARD_TOOLS


async def execute_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Execute tool calls locally with real implementations. Returns tool results."""
    results = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = fn.get("name") or tc.get("name")
        args_str = fn.get("arguments", "{}") if isinstance(fn.get("arguments", "{}"), str) else "{}"
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except Exception as e:
            _log.debug("tool args parse failed for %s: %s", name, e)
            args = {}
        impl = _TOOL_IMPL.get(str(name or ""))
        if not impl:
            results.append({
                "tool_call_id": tc.get("id") or "call_unknown",
                "role": "tool",
                "name": str(name),
                "content": json.dumps({"status": "error", "error": f"unknown tool: {name}"}, ensure_ascii=False),
            })
            continue
        try:
            res = await impl(args) if inspect.iscoroutinefunction(impl) else impl(args)
            _log.info("tool %s -> %s", name, res.get("status") if isinstance(res, dict) else res)
            results.append({
                "tool_call_id": tc.get("id") or "call_unknown",
                "role": "tool",
                "name": str(name),
                "content": json.dumps(res, ensure_ascii=False),
            })
        except Exception as e:
            _log.warning("tool %s execution failed: %s", name, e)
            results.append({
                "tool_call_id": tc.get("id") or "call_unknown",
                "role": "tool",
                "name": str(name),
                "content": json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False),
            })
    return results


def synthesize_tool_calls_from_content(msg: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """If message contains tool_calls in content, extract and normalize them."""
    content = msg.get("content")
    if not isinstance(content, str):
        return msg
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "tool_calls" in parsed:
            tc_list = parsed["tool_calls"]
            if isinstance(tc_list, list) and tc_list:
                msg["tool_calls"] = tc_list
                msg["content"] = None
    except Exception as e:
        _log.debug("synthesize tool_calls from content failed: %s", e)
    return msg


async def stream_with_tools(payload: dict[str, Any], upstream_stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Process streaming response and inject tool_calls if synthesized."""
    async for chunk in upstream_stream:
        if chunk:
            _metrics.record("stream_chunk_out", 1)
            yield chunk
