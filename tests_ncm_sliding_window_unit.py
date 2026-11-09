"""Unit tests for sliding window context management."""
from __future__ import annotations
import unittest
from app.ncm.thinker_lite import SlidingWindowContext


class SlidingWindowContextTests(unittest.TestCase):
    def setUp(self):
        self.window = SlidingWindowContext(
            max_tokens=128,
            keep_last_messages=4
        )

    def test_estimate_tokens(self):
        self.assertEqual(self.window.estimate_tokens("hello"), 1)
        self.assertEqual(self.window.estimate_tokens("a" * 100), 25)
        self.assertEqual(self.window.estimate_tokens(""), 1)

    def test_count_messages_tokens(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        count = self.window.count_messages_tokens(messages)
        self.assertGreater(count, 0)

    def test_no_compression_needed(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = self.window.compress(messages)
        self.assertEqual(result, messages)

    def test_compress_drops_old_messages(self):
        messages = [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "second message"},
            {"role": "assistant", "content": "second response"},
            {"role": "user", "content": "third message"},
            {"role": "assistant", "content": "third response"},
            {"role": "user", "content": "fourth message"},
            {"role": "assistant", "content": "fourth response"},
        ]
        # 8 messages, keep_last=4, should keep last 4 + summary
        result = self.window.compress(messages)
        # Should have system + summary + 4 kept = at least 3 messages
        self.assertGreaterEqual(len(result), 3)
        # Last 4 should be preserved
        self.assertEqual(result[-1]["content"], "fourth response")
        self.assertEqual(result[-2]["content"], "fourth message")
        self.assertEqual(result[-3]["content"], "third response")
        self.assertEqual(result[-4]["content"], "third message")

    def test_preserves_system_message(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = self.window.compress(messages)
        # System message should be first
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[0]["content"], "You are a helpful assistant")

    def test_keeps_last_n_messages(self):
        window = SlidingWindowContext(max_tokens=128, keep_last_messages=2)
        messages = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "resp1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "resp2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "resp3"},
        ]
        result = window.compress(messages)
        # Should keep last 2 messages + summary
        self.assertEqual(result[-2]["content"], "msg3")
        self.assertEqual(result[-1]["content"], "resp3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
