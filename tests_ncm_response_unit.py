"""Deterministic tests for the NCM response contract (no model, no network).

Run: .venv/bin/python -m unittest tests_ncm_response_unit.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "local" / "ncm"))

import response_builder as builder


class CompletionTests(unittest.TestCase):
    def test_single_sample_usage(self):
        body = builder.build_completion(
            model_id="ncm-lm1b-large",
            texts=["one sample"],
            latency_ms=350,
            completion_id="chatcmpl-test",
            created=123,
            tokens_per_sample=128,
        )
        self.assertEqual(body["object"], "chat.completion")
        self.assertEqual(body["model"], "ncm-lm1b-large")
        self.assertEqual(body["id"], "chatcmpl-test")
        self.assertEqual(body["created"], 123)
        self.assertEqual(len(body["choices"]), 1)
        self.assertEqual(body["usage"]["completion_tokens"], 128)
        self.assertEqual(body["usage"]["total_tokens"], 128)
        self.assertEqual(body["gateway"]["batch"], 1)
        self.assertTrue(body["gateway"]["prompt_ignored"])

    def test_four_samples_expose_all_choices_and_usage(self):
        texts = ["a", "b", "c", "d"]
        body = builder.build_completion(
            model_id="ncm-lm1b-large",
            texts=texts,
            latency_ms=760,
            completion_id="chatcmpl-test",
            created=123,
            tokens_per_sample=128,
        )
        self.assertEqual([choice["index"] for choice in body["choices"]], [0, 1, 2, 3])
        self.assertEqual(
            [choice["message"]["content"] for choice in body["choices"]], texts
        )
        self.assertEqual(body["usage"]["completion_tokens"], 512)
        self.assertEqual(body["usage"]["total_tokens"], 512)
        self.assertEqual(body["gateway"]["batch"], 4)
        self.assertEqual(body["gateway"]["samples"], 4)

    def test_rejects_empty_or_blank_texts(self):
        for texts in ([], [""], ["ok", "   "]):
            with self.subTest(texts=texts):
                with self.assertRaises(ValueError):
                    builder.build_completion(
                        model_id="ncm-lm1b-large",
                        texts=texts,
                        latency_ms=1,
                        completion_id="chatcmpl-test",
                        created=1,
                        tokens_per_sample=128,
                    )

    def test_rejects_non_positive_tokens(self):
        with self.assertRaises(ValueError):
            builder.build_completion(
                model_id="ncm-lm1b-large",
                texts=["x"],
                latency_ms=1,
                completion_id="chatcmpl-test",
                created=1,
                tokens_per_sample=0,
            )


class StreamTests(unittest.TestCase):
    def test_two_samples_have_two_content_chunks_and_all_stops(self):
        chunks = builder.build_stream_chunks(
            model_id="ncm-lm1b-large",
            texts=["first", "second"],
            latency_ms=460,
            completion_id="chatcmpl-test",
            created=123,
            tokens_per_sample=128,
        )
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["choices"][0]["index"], 0)
        self.assertEqual(chunks[0]["choices"][0]["delta"]["content"], "first")
        self.assertEqual(chunks[1]["choices"][0]["index"], 1)
        self.assertEqual(chunks[1]["choices"][0]["delta"]["content"], "second")
        final = chunks[-1]
        self.assertEqual(
            [choice["finish_reason"] for choice in final["choices"]],
            ["stop", "stop"],
        )
        self.assertEqual(final["usage"]["completion_tokens"], 256)
        self.assertEqual(final["gateway"]["batch"], 2)

    def test_stream_rejects_empty_texts(self):
        with self.assertRaises(ValueError):
            builder.build_stream_chunks(
                model_id="ncm-lm1b-large",
                texts=[],
                latency_ms=1,
                completion_id="chatcmpl-test",
                created=1,
                tokens_per_sample=128,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
