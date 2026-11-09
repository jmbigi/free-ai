"""MCP (Model Context Protocol) server for the Free AI Gateway.

Exposes gateway tools and resources via MCP stdio/SSE/WebSocket transports.
Clients (KimiCode, OpenCode, etc.) connect via MCP instead of custom APIs.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
import subprocess
import tempfile
import shlex
import signal
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# --- MCP Protocol Types ---

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class MCPTool(BaseModel):
    name: str
    description: str
    inputSchema: dict[str, Any]


class MCPResource(BaseModel):
    uri: str
    name: str
    description: str | None = None
    mimeType: str | None = None


# --- Tool Implementations ---

@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[dict[str, Any]]:
        return [
            MCPTool(name=t.name, description=t.description, inputSchema=t.input_schema).model_dump()
            for t in self._tools.values()
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Tool not found: {name}")
        return await tool.handler(arguments)


# --- Sandboxed Code Execution ---

class SandboxExecutor:
    """Secure sandbox for code execution with resource limits."""
    
    def __init__(
        self,
        timeout: int = 30,
        max_memory_mb: int = 256,
        max_cpu_seconds: int = 30,
        allowed_imports: Optional[list[str]] = None,
        blocked_imports: Optional[list[str]] = None,
    ):
        self.timeout = timeout
        self.max_memory_mb = max_memory_mb
        self.max_cpu_seconds = max_cpu_seconds
        self.allowed_imports = set(allowed_imports or [])
        self.blocked_imports = set(blocked_imports or [
            "os", "subprocess", "sys", "shutil", "pathlib",
            "socket", "urllib", "requests", "http",
            "ctypes", "multiprocessing", "threading",
            "importlib", "pkgutil", "runpy",
        ])
    
    def _create_sandbox_script(self, code: str, timeout: int) -> str:
        """Create a sandboxed Python script with resource limits."""
        blocked_repr = "{" + ", ".join(f'"{x}"' for x in self.blocked_imports) + "}"
        allowed_repr = "{" + ", ".join(f'"{x}"' for x in self.allowed_imports) + "}" if self.allowed_imports else "set()"
        
        return f'''
import sys
import resource
import signal
import sys
import os

# Set resource limits
try:
    resource.setrlimit(resource.RLIMIT_CPU, ({self.max_cpu_seconds}, {self.max_cpu_seconds}))
    resource.setrlimit(resource.RLIMIT_AS, ({self.max_memory_mb * 1024 * 1024}, {self.max_memory_mb * 1024 * 1024}))
    resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))  # 10MB max file size
except:
    pass

# Block dangerous imports
import builtins
original_import = builtins.__import__

blocked = {blocked_repr}
allowed = {allowed_repr}
# Modules needed by sandbox internals - never block these
_sandbox_allowed = {{"sys", "resource", "signal", "traceback", "builtins", "io"}}

def safe_import(name, *args, **kwargs):
    if name in _sandbox_allowed:
        return original_import(name, *args, **kwargs)
    if name in blocked:
        raise ImportError(f"Import blocked: {{name}}")
    if allowed and name not in allowed and not name.startswith("_"):
        pass
    return original_import(name, *args, **kwargs)

builtins.__import__ = safe_import

# Redirect stdout/stderr - save real ones first
import sys
from io import StringIO
_real_stdout = sys.stdout
_real_stderr = sys.stderr

_stdout = StringIO()
_stderr = StringIO()
sys.stdout = _stdout
sys.stderr = _stderr

# User code
try:
{chr(10).join("    " + line for line in code.split(chr(10)))}
except Exception as e:
    _real_stderr.write(f"{{type(e).__name__}}: {{e}}\\n")
    import traceback
    traceback.print_exc(file=_real_stderr)
    sys.exit(1)

# Restore real stdout/stderr for markers
sys.stdout = _real_stdout
sys.stderr = _real_stderr

# Output results
print("__MCP_STDOUT__")
print(_stdout.getvalue())
print("__MCP_STDERR__")
print(_stderr.getvalue())
'''
    
    async def execute(self, code: str, timeout: Optional[int] = None) -> dict[str, Any]:
        """Execute Python code in sandbox."""
        timeout = timeout or self.timeout
        script = self._create_sandbox_script(code, timeout)
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script)
            path = f.name
        
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                # Parse the special output markers
                stdout_text = stdout.decode(errors="replace")
                stderr_text = stderr.decode(errors="replace")
                
                # Extract stdout/stderr from our markers
                user_stdout = ""
                user_stderr = ""
                if "__MCP_STDOUT__" in stdout_text:
                    parts = stdout_text.split("__MCP_STDOUT__", 1)
                    if len(parts) > 1:
                        user_stdout = parts[1].split("__MCP_STDERR__")[0]
                if "__MCP_STDERR__" in stdout_text:
                    parts = stdout_text.split("__MCP_STDERR__", 1)
                    if len(parts) > 1:
                        user_stderr = parts[1]
                
                return {
                    "exit_code": proc.returncode,
                    "stdout": user_stdout,
                    "stderr": user_stderr or stderr_text,
                }
            except asyncio.TimeoutError:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except:
                    proc.kill()
                await proc.wait()
                return {"error": "timeout", "exit_code": -1, "stdout": "", "stderr": "Execution timeout"}
            except Exception as e:
                return {"error": str(e), "exit_code": -1, "stdout": "", "stderr": str(e)}
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


# --- Built-in Tools ---

async def _web_search(args: dict[str, Any]) -> dict[str, Any]:
    """Search the web via gateway's search endpoint."""
    from app.search import web_search
    query = args.get("query", "")
    max_results = int(args.get("max_results", 5))
    results = await web_search(query, max_results=max_results)
    return {"results": results}


async def _code_exec(args: dict[str, Any]) -> dict[str, Any]:
    """Execute Python code in a sandbox."""
    code = args.get("code", "")
    timeout = int(args.get("timeout", 30))
    sandbox = SandboxExecutor(timeout=timeout)
    return await sandbox.execute(code, timeout)


async def _bash_exec(args: dict[str, Any]) -> dict[str, Any]:
    """Execute bash command in restricted environment."""
    cmd = args.get("command", "")
    timeout = int(args.get("timeout", 30))
    cwd = args.get("cwd", "/tmp/mcp-tools")
    
    # Security: only allow specific safe commands
    allowed_prefixes = ["ls", "cat", "head", "tail", "grep", "find", "wc", "echo", "pwd", "python3", "pip"]
    cmd_parts = shlex.split(cmd)
    if not cmd_parts or cmd_parts[0] not in allowed_prefixes:
        return {"error": f"Command not allowed: {cmd_parts[0] if cmd_parts else 'empty'}", "exit_code": -1}
    
    # Restrict to allowed directory
    abs_cwd = os.path.abspath(cwd)
    allowed_root = os.path.abspath(os.environ.get("MCP_TOOLS_ROOT", "/tmp/mcp-tools"))
    if not abs_cwd.startswith(allowed_root):
        return {"error": "cwd outside allowed root", "exit_code": -1}
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            cwd=abs_cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "exit_code": proc.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": "timeout", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}


async def _file_read(args: dict[str, Any]) -> dict[str, Any]:
    """Read a file from the allowed root."""
    root = os.environ.get("MCP_TOOLS_ROOT", "/tmp/mcp-tools")
    path = args.get("path", "")
    abs_path = os.path.abspath(os.path.join(root, path))
    if not abs_path.startswith(os.path.abspath(root)):
        return {"error": "path traversal not allowed"}
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        return {"error": str(e)}


async def _file_write(args: dict[str, Any]) -> dict[str, Any]:
    """Write a file to the allowed root."""
    root = os.environ.get("MCP_TOOLS_ROOT", "/tmp/mcp-tools")
    path = args.get("path", "")
    content = args.get("content", "")
    abs_path = os.path.abspath(os.path.join(root, path))
    if not abs_path.startswith(os.path.abspath(root)):
        return {"error": "path traversal not allowed"}
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "bytes": len(content.encode())}
    except Exception as e:
        return {"error": str(e)}


async def _file_list(args: dict[str, Any]) -> dict[str, Any]:
    """List files in a directory."""
    root = os.environ.get("MCP_TOOLS_ROOT", "/tmp/mcp-tools")
    path = args.get("path", ".")
    abs_path = os.path.abspath(os.path.join(root, path))
    if not abs_path.startswith(os.path.abspath(root)):
        return {"error": "path traversal not allowed"}
    try:
        entries = []
        for entry in os.scandir(abs_path):
            entries.append({
                "name": entry.name,
                "type": "dir" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else None,
            })
        return {"entries": entries}
    except Exception as e:
        return {"error": str(e)}


async def _kb_query(args: dict[str, Any]) -> dict[str, Any]:
    """Query the gateway knowledge base."""
    from app.knowledge import query as kb_query
    q = args.get("query", "")
    k = int(args.get("k", 5))
    results = await kb_query(q, k=k)
    return {"results": results}


# --- Resource Implementations ---

class ResourceRegistry:
    def __init__(self):
        self._resources: dict[str, tuple[str, str, str | None, Callable[[], Any]]] = {}

    def register(self, uri: str, name: str, description: str | None, mime: str | None, handler: Callable[[], Any]) -> None:
        self._resources[uri] = (name, description, mime, handler)

    def list(self) -> list[MCPResource]:
        return [
            MCPResource(uri=uri, name=name, description=desc, mimeType=mime)
            for uri, (name, desc, mime, _) in self._resources.items()
        ]

    async def read(self, uri: str) -> dict[str, Any]:
        entry = self._resources.get(uri)
        if not entry:
            raise ValueError(f"Resource not found: {uri}")
        _, _, mime, handler = entry
        content = await handler()
        return {"contents": [{"uri": uri, "mimeType": mime, "text": content}]}


# --- MCP Server ---

class MCPServer:
    def __init__(self):
        self.tools = ToolRegistry()
        self.resources = ResourceRegistry()
        self._register_builtin()

    def _register_builtin(self) -> None:
        # Tools
        self.tools.register(Tool(
            name="web_search",
            description="Search the web for current information",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            handler=_web_search,
        ))
        self.tools.register(Tool(
            name="code_exec",
            description="Execute Python code in a secure sandbox",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "default": 30},
                },
                "required": ["code"],
            },
            handler=_code_exec,
        ))
        self.tools.register(Tool(
            name="bash_exec",
            description="Execute bash command (restricted to safe commands)",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Bash command to execute"},
                    "timeout": {"type": "integer", "default": 30},
                    "cwd": {"type": "string", "default": "/tmp/mcp-tools"},
                },
                "required": ["command"],
            },
            handler=_bash_exec,
        ))
        self.tools.register(Tool(
            name="file_read",
            description="Read a file from the workspace",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=_file_read,
        ))
        self.tools.register(Tool(
            name="file_write",
            description="Write a file to the workspace",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=_file_write,
        ))
        self.tools.register(Tool(
            name="file_list",
            description="List files in a directory",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
            },
            handler=_file_list,
        ))
        self.tools.register(Tool(
            name="kb_query",
            description="Query the gateway knowledge base",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            handler=_kb_query,
        ))

        # Resources
        async def _api_docs() -> str:
            from app.help_page import help_payload
            return json.dumps(help_payload(), indent=2, ensure_ascii=False)
        self.resources.register(
            "docs://api", "API Documentation", "Gateway API reference", "application/json", _api_docs
        )

        async def _models_list() -> str:
            from app.router import catalog
            _, models = await catalog()
            return json.dumps([m.__dict__ for m in models], indent=2, ensure_ascii=False)
        self.resources.register(
            "docs://models", "Available Models", "List of all models with capabilities", "application/json", _models_list
        )

    # --- JSON-RPC Methods ---

    async def handle(self, request: MCPRequest) -> MCPResponse:
        try:
            if request.method == "initialize":
                return MCPResponse(id=request.id, result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "free-ai-gateway", "version": "2.3.0"},
                })
            elif request.method == "tools/list":
                return MCPResponse(id=request.id, result={"tools": self.tools.list()})
            elif request.method == "tools/call":
                params = request.params or {}
                name = params.get("name")
                arguments = params.get("arguments", {})
                result = await self.tools.call(name, arguments)
                return MCPResponse(id=request.id, result={"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
            elif request.method == "resources/list":
                return MCPResponse(id=request.id, result={"resources": self.resources.list()})
            elif request.method == "resources/read":
                params = request.params or {}
                uri = params.get("uri")
                result = await self.resources.read(uri)
                return MCPResponse(id=request.id, result=result)
            elif request.method == "notifications/initialized":
                return MCPResponse(id=request.id, result={})
            else:
                return MCPResponse(id=request.id, error={"code": -32601, "message": f"Method not found: {request.method}"})
        except Exception as e:
            return MCPResponse(id=request.id, error={"code": -32603, "message": str(e)})


# --- FastAPI App (SSE + WebSocket Transports) ---

app = FastAPI(title="Free AI Gateway MCP Server")
_mcp = MCPServer()


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    body = await request.json()
    req = MCPRequest(**body)
    resp = await _mcp.handle(req)
    return resp.model_dump(exclude_none=True)


@app.get("/mcp/sse")
async def mcp_sse(request: Request):
    """SSE transport for MCP (long-lived connection)."""
    async def event_gen():
        # Send initial capabilities
        yield f"data: {json.dumps({'jsonrpc':'2.0','method':'notifications/initialized','params':{}})}\n\n"
        # Keep alive
        while True:
            await asyncio.sleep(30)
            yield ": keepalive\n\n"
    return StreamingResponse(event_gen(), media_type="text/event-stream")


# --- WebSocket Transport ---

@app.websocket("/mcp/ws")
async def mcp_websocket(websocket: WebSocket):
    """WebSocket transport for MCP (bidirectional)."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                req = MCPRequest.model_validate_json(data)
            except Exception as e:
                await websocket.send_text(MCPResponse(id=None, error={"code": -32700, "message": f"Parse error: {e}"}).model_dump_json(exclude_none=True))
                continue
            resp = await _mcp.handle(req)
            await websocket.send_text(resp.model_dump_json(exclude_none=True))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# --- SSE with Request/Response (for clients that need request-response over SSE) ---

@app.post("/mcp/sse")
async def mcp_sse_post(request: Request):
    """SSE transport with POST request (for clients that can't use WebSocket)."""
    body = await request.json()
    req = MCPRequest(**body)
    resp = await _mcp.handle(req)
    return StreamingResponse(
        iter([f"data: {resp.model_dump_json(exclude_none=True)}\n\n"]),
        media_type="text/event-stream"
    )


# --- STDIO Transport (for CLI clients) ---

async def run_stdio():
    """Run MCP server over stdio (for KimiCode, OpenCode, etc.)."""
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    writer = sys.stdout

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            req = MCPRequest.model_validate_json(line.decode())
        except Exception:
            continue
        resp = await _mcp.handle(req)
        writer.write((resp.model_dump_json(exclude_none=True) + "\n").encode())
        await writer.drain()


# --- FastAPI App for HTTP ---

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stdio":
        asyncio.run(run_stdio())
    else:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=11439)