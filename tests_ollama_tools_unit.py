"""Pure unit tests for Ollama <-> OpenAI tool-call compatibility.

Run: .venv/bin/python -m unittest tests_ollama_tools_unit.py -v
"""
from __future__ import annotations

import json
import unittest

from app.providers.ollama_tools import (
    build_completion,
    normalize_tool_calls,
    stream_delta,
    text_content,
    to_ollama_messages,
)


class ToolNormalizationTests(unittest.TestCase):
    def test_ollama_arguments_object_to_openai_string(self):
        calls = normalize_tool_calls(
            [{"function": {"name": "read_file", "arguments": {"path": "a.txt"}}}]
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["type"], "function")
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "a.txt"})
        self.assertTrue(calls[0]["id"].startswith("call_"))

    def test_openai_arguments_string_is_preserved(self):
        calls = normalize_tool_calls(
            [{"id": "call_x", "function": {"name": "grep", "arguments": '{"q":"x"}'}}]
        )
        self.assertEqual(calls[0]["id"], "call_x")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"q": "x"})


class MessageConversionTests(unittest.TestCase):
    def test_preserves_assistant_tool_calls_and_tool_result(self):
        messages = [
            {"role": "user", "content": "lee el archivo"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "contenido"},
        ]
        converted = to_ollama_messages(messages)
        self.assertEqual(converted[1]["role"], "assistant")
        self.assertEqual(converted[1]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(converted[1]["tool_calls"][0]["function"]["arguments"], {"path": "a.txt"})
        self.assertEqual(converted[2]["role"], "tool")
        self.assertEqual(converted[2]["tool_name"], "read_file")

    def test_developer_maps_to_system_and_list_content_flattens(self):
        converted = to_ollama_messages(
            [
                {"role": "developer", "content": [{"type": "text", "text": "sistema"}]},
                {"role": "user", "content": "hola"},
            ]
        )
        self.assertEqual(converted[0], {"role": "system", "content": "sistema"})
        self.assertEqual(converted[1]["content"], "hola")


class CompletionTests(unittest.TestCase):
    def test_tool_only_message_is_not_empty_error(self):
        body = build_completion(
            model="qwen3-coder-opt:latest",
            content="",
            thinking="",
            raw_tool_calls=[
                {"function": {"name": "write_file", "arguments": {"path": "x", "content": "y"}}}
            ],
            prompt_tokens=10,
            completion_tokens=5,
            completion_id="chatcmpl-test",
            created=1,
        )
        choice = body["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertEqual(choice["message"]["content"], "")
        self.assertEqual(choice["message"]["tool_calls"][0]["function"]["name"], "write_file")
        self.assertEqual(body["gateway"]["tool_calls"], 1)

    def test_normal_content_finish_stop(self):
        body = build_completion(
            model="m",
            content="hola",
            thinking="",
            raw_tool_calls=[],
            prompt_tokens=1,
            completion_tokens=1,
            completion_id="chatcmpl-test",
            created=1,
        )
        self.assertEqual(body["choices"][0]["finish_reason"], "stop")
        self.assertEqual(body["choices"][0]["message"]["content"], "hola")


class StreamDeltaTests(unittest.TestCase):
    def test_tool_delta_has_index_and_arguments(self):
        delta = stream_delta(
            content="",
            thinking="",
            raw_tool_calls=[{"function": {"name": "list_dir", "arguments": {"path": "."}}}],
        )
        self.assertEqual(delta["tool_calls"][0]["index"], 0)
        self.assertEqual(delta["tool_calls"][0]["function"]["name"], "list_dir")
        self.assertEqual(json.loads(delta["tool_calls"][0]["function"]["arguments"]), {"path": "."})

    def test_text_content_variants(self):
        self.assertEqual(text_content(None), "")
        self.assertEqual(text_content("x"), "x")
        self.assertEqual(text_content([{"text": "a"}, {"content": "b"}]), "a\nb")


if __name__ == "__main__":
    unittest.main(verbosity=2)
