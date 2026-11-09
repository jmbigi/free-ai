"""Unit tests for llama-cpp-python/Qwen3-Coder tool compatibility.

Run: .venv/bin/python -m unittest tests_llamacpp_tools_unit.py -v
"""
from __future__ import annotations

import json
import unittest

from app.providers.llamacpp_tools import (
    extract_content_tool_calls,
    openai_tool_calls,
    to_llamacpp_messages,
)
from app.providers.configured import LlamaCppLocalProvider


class ContentToolCallTests(unittest.TestCase):
    def test_xml_tool_call(self):
        content = (
            "<tool_call>\n<function=write_file>\n"
            "<parameter=path>\nx.txt\n</parameter>\n"
            "<parameter=content>\nok\n</parameter>\n"
            "</function>\n</tool_call>"
        )
        clean, calls = extract_content_tool_calls(content)
        self.assertEqual(clean, "")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "write_file")
        args = json.loads(calls[0]["function"]["arguments"])
        self.assertEqual(args, {"path": "x.txt", "content": "ok"})

    def test_json_tool_call_in_wrapper(self):
        content = '<tool_call>{"name": "grep", "arguments": {"q": "x"}}</tool_call>'
        clean, calls = extract_content_tool_calls(content)
        self.assertEqual(clean, "")
        self.assertEqual(calls[0]["function"]["name"], "grep")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"q": "x"})

    def test_multiple_calls_and_text(self):
        content = (
            "Voy a ejecutar dos herramientas.\n"
            "<tool_call><function=read_file><parameter=path>a</parameter></function></tool_call>\n"
            "<tool_call><function=read_file><parameter=path>b</parameter></function></tool_call>"
        )
        clean, calls = extract_content_tool_calls(content)
        self.assertEqual(clean, "Voy a ejecutar dos herramientas.")
        self.assertEqual([c["function"]["name"] for c in calls], ["read_file", "read_file"])
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "a"})

    def test_bare_json_requires_opt_in(self):
        content = '{"name": "x", "arguments": {}}'
        clean, calls = extract_content_tool_calls(content)
        self.assertEqual(calls, [])
        self.assertEqual(clean, content)
        clean2, calls2 = extract_content_tool_calls(content, allow_bare_json=True)
        self.assertEqual(clean2, "")
        self.assertEqual(calls2[0]["function"]["name"], "x")

    def test_plain_text_untouched(self):
        clean, calls = extract_content_tool_calls("hola")
        self.assertEqual(clean, "hola")
        self.assertEqual(calls, [])


class MessageConversionTests(unittest.TestCase):
    def test_arguments_string_to_mapping(self):
        messages = [
            {"role": "user", "content": "x"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "write_file", "arguments": '{"path":"x","content":"ok"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "write_file", "content": "ok"},
        ]
        converted = to_llamacpp_messages(messages)
        self.assertNotIn("tool_calls", converted[1])
        self.assertIn("<function=write_file>", converted[1]["content"])
        self.assertIn("<parameter=path>\nx\n</parameter>", converted[1]["content"])
        self.assertIn("<parameter=content>\nok\n</parameter>", converted[1]["content"])
        self.assertEqual(converted[2]["role"], "tool")
        self.assertEqual(converted[2]["tool_call_id"], "call_1")

    def test_invalid_arguments_become_empty_mapping(self):
        converted = to_llamacpp_messages([
            {"role": "assistant", "tool_calls": [{"function": {"name": "x", "arguments": "not-json"}}]}
        ])
        self.assertNotIn("tool_calls", converted[0])
        self.assertIn("<function=x>", converted[0]["content"])

    def test_tool_result_without_id_becomes_user(self):
        converted = to_llamacpp_messages([{"role": "tool", "content": "ok"}])
        self.assertEqual(converted[0]["role"], "user")
        self.assertIn("Tool result", converted[0]["content"])

    def test_existing_tool_calls_normalized(self):
        calls = openai_tool_calls([
            {"id": "call_x", "function": {"name": "read_file", "arguments": {"path": "a"}}}
        ])
        self.assertEqual(calls[0]["id"], "call_x")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "a"})


class ProviderResponseTests(unittest.TestCase):
    def _resp(self, content):
        return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}

    def test_xml_response_becomes_tool_calls(self):
        data = self._resp("<tool_call><function=read_file><parameter=path>a</parameter></function></tool_call>")
        out = LlamaCppLocalProvider._convert_response(data, "local-llamacpp/x", "local-llamacpp", allow_bare_json=True)
        choice = out["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertEqual(choice["message"]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(out["gateway"]["tool_calls"], 1)

    def test_bare_json_is_not_tool_call_without_tools(self):
        data = self._resp('{"name": "read_file", "arguments": {"path": "a"}}')
        out = LlamaCppLocalProvider._convert_response(data, "local-llamacpp/x", "local-llamacpp", allow_bare_json=False)
        self.assertEqual(out["choices"][0]["finish_reason"], "stop")
        self.assertNotIn("tool_calls", out["choices"][0]["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
