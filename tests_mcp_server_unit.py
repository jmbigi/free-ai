"""Unit tests for MCP server enhancements."""
from __future__ import annotations

import asyncio
import json
import unittest

from app.mcp.server import MCPServer, MCPRequest, SandboxExecutor


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.mcp = MCPServer()

    def test_initialize(self):
        req = MCPRequest(id=1, method="initialize")
        resp = asyncio.run(self.mcp.handle(req))
        self.assertEqual(resp.result["protocolVersion"], "2024-11-05")
        self.assertEqual(resp.result["serverInfo"]["name"], "free-ai-gateway")

    def test_tools_list(self):
        req = MCPRequest(id=2, method="tools/list")
        resp = asyncio.run(self.mcp.handle(req))
        tools = resp.result["tools"]
        self.assertGreaterEqual(len(tools), 7)
        tool_names = {t["name"] for t in tools}
        expected = {"web_search", "code_exec", "bash_exec", "file_read", "file_write", "file_list", "kb_query"}
        self.assertTrue(expected.issubset(tool_names))

    def test_resources_list(self):
        req = MCPRequest(id=3, method="resources/list")
        resp = asyncio.run(self.mcp.handle(req))
        resources = resp.result["resources"]
        self.assertGreaterEqual(len(resources), 2)
        uris = {r.uri for r in resources}
        self.assertIn("docs://api", uris)
        self.assertIn("docs://models", uris)

    def test_unknown_method(self):
        req = MCPRequest(id=4, method="unknown/method")
        resp = asyncio.run(self.mcp.handle(req))
        self.assertIsNotNone(resp.error)
        self.assertEqual(resp.error["code"], -32601)

    def test_tools_call_web_search(self):
        req = MCPRequest(id=5, method="tools/call", params={"name": "web_search", "arguments": {"query": "test", "max_results": 2}})
        resp = asyncio.run(self.mcp.handle(req))
        self.assertIn("content", resp.result)

    def test_tools_call_file_write_read(self):
        # Write
        req = MCPRequest(id=6, method="tools/call", params={"name": "file_write", "arguments": {"path": "test_mcp.txt", "content": "hello mcp"}})
        resp = asyncio.run(self.mcp.handle(req))
        self.assertIn("ok", str(resp.result))
        
        # Read
        req = MCPRequest(id=7, method="tools/call", params={"name": "file_read", "arguments": {"path": "test_mcp.txt"}})
        resp = asyncio.run(self.mcp.handle(req))
        content = json.loads(resp.result["content"][0]["text"])
        self.assertEqual(content["content"], "hello mcp")

    def test_tools_call_file_list(self):
        req = MCPRequest(id=8, method="tools/call", params={"name": "file_list", "arguments": {"path": "."}})
        resp = asyncio.run(self.mcp.handle(req))
        self.assertIn("entries", str(resp.result))

    def test_notifications_initialized(self):
        req = MCPRequest(id=9, method="notifications/initialized", params={})
        resp = asyncio.run(self.mcp.handle(req))
        self.assertEqual(resp.result, {})


class SandboxExecutorTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = SandboxExecutor(timeout=10)

    def test_basic_execution(self):
        result = asyncio.run(self.sandbox.execute("print('hello')"))
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello", result["stdout"])

    def test_stderr_capture(self):
        result = asyncio.run(self.sandbox.execute("import sys; sys.stderr.write('error msg')"))
        self.assertIn("error msg", result["stderr"])

    def test_exception_handling(self):
        result = asyncio.run(self.sandbox.execute("raise ValueError('test error')"))
        self.assertNotEqual(result["exit_code"], 0)
        self.assertIn("ValueError", result["stderr"])

    def test_import_blocking(self):
        # This should fail due to blocked imports (runtime import inside function)
        result = asyncio.run(self.sandbox.execute("def foo(): import os\nfoo()"))
        self.assertNotEqual(result["exit_code"], 0)
        self.assertIn("ImportError", result["stderr"])

    def test_timeout(self):
        sandbox = SandboxExecutor(timeout=1)
        result = asyncio.run(sandbox.execute("import time; time.sleep(5)"))
        self.assertEqual(result["exit_code"], -1)
        self.assertIn("timeout", result.get("error", "").lower())
        self.assertEqual(result["stdout"], "")
        self.assertEqual(result["stderr"], "Execution timeout")

    def test_memory_limit(self):
        sandbox = SandboxExecutor(max_memory_mb=1)
        result = asyncio.run(sandbox.execute("x = 'x' * (100 * 1024 * 1024)"))  # 100MB
        # Should be killed by memory limit
        self.assertNotEqual(result["exit_code"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)