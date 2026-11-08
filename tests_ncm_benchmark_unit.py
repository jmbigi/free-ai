"""Deterministic unit tests for the local NCM benchmark helpers (no network).

Run: .venv/bin/python -m unittest tests_ncm_benchmark_unit.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "local" / "ncm"))

import benchmark_ncm as bench


class PercentileTests(unittest.TestCase):
    def test_nearest_rank(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertEqual(bench.percentile(values, 0), 10.0)
        self.assertEqual(bench.percentile(values, 50), 30.0)
        self.assertEqual(bench.percentile(values, 95), 50.0)
        self.assertEqual(bench.percentile(values, 100), 50.0)

    def test_single_value(self):
        self.assertEqual(bench.percentile([7.0], 95), 7.0)

    def test_rejects_empty_and_bad_percentile(self):
        with self.assertRaises(ValueError):
            bench.percentile([], 50)
        with self.assertRaises(ValueError):
            bench.percentile([1.0], -1)


class SummarizeTests(unittest.TestCase):
    def test_summary_fields(self):
        summary = bench.summarize([10.0, 20.0, 30.0])
        self.assertEqual(summary["count"], 3)
        self.assertEqual(summary["min"], 10.0)
        self.assertEqual(summary["p50"], 20.0)
        self.assertEqual(summary["p95"], 30.0)
        self.assertEqual(summary["max"], 30.0)
        self.assertEqual(summary["mean"], 20.0)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            bench.summarize([])


class ParseBatchesTests(unittest.TestCase):
    def test_accepts_supported_batches(self):
        self.assertEqual(bench.parse_batches("1,2,4"), [1, 2, 4])
        self.assertEqual(bench.parse_batches(" 1 , 1 , 2 "), [1, 2])

    def test_rejects_out_of_range_and_empty(self):
        with self.assertRaises(ValueError):
            bench.parse_batches("0")
        with self.assertRaises(ValueError):
            bench.parse_batches("5")
        with self.assertRaises(ValueError):
            bench.parse_batches("")
        with self.assertRaises(ValueError):
            bench.parse_batches("1,x")


class ValidateResponseTests(unittest.TestCase):
    @staticmethod
    def _response(batch: int, *, reported: int = 128, content: str = "text") -> dict:
        return {
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}}
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": reported},
            "gateway": {
                "unconditional": True,
                "prompt_ignored": True,
                "fixed_length": 128,
            },
        }

    def test_batch_one_matches_usage(self):
        check = bench.validate_chat_response(
            self._response(1), batch=1
        )
        self.assertTrue(check["usage_matches_batch"])
        self.assertFalse(check["single_choice_for_batch"])
        self.assertTrue(check["prompt_ignored"])
        self.assertEqual(check["expected_completion_tokens"], 128)

    def test_batch_four_with_stale_usage_is_flagged(self):
        check = bench.validate_chat_response(
            self._response(4, reported=128), batch=4
        )
        self.assertFalse(check["usage_matches_batch"])
        self.assertTrue(check["single_choice_for_batch"])
        self.assertEqual(check["expected_completion_tokens"], 512)

    def test_batch_four_correct_contract(self):
        data = self._response(4, reported=512)
        data["choices"] = [
            {"index": index, "message": {"role": "assistant", "content": f"t{index}"}}
            for index in range(4)
        ]
        check = bench.validate_chat_response(data, batch=4)
        self.assertTrue(check["usage_matches_batch"])
        self.assertFalse(check["single_choice_for_batch"])
        self.assertEqual(check["choices_count"], 4)

    def test_empty_content_is_rejected(self):
        with self.assertRaises(RuntimeError):
            bench.validate_chat_response(
                self._response(1, content="   "), batch=1
            )

    def test_missing_choices_is_rejected(self):
        with self.assertRaises(RuntimeError):
            bench.validate_chat_response({}, batch=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
