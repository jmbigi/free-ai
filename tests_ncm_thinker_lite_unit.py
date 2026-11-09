"""Unit tests for gateway thinker-lite (app/ncm/thinker_lite.py)."""
from __future__ import annotations

import unittest

from app.ncm.thinker_lite import ThinkerLite, apply_thinker_lite, math_answer


class MathAnswerTests(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(math_answer("what is 2 plus 3"), "2 + 3 = 5")
        self.assertEqual(math_answer("calculate 10 minus 4"), "10 - 4 = 6")
        self.assertEqual(math_answer("5 times 6"), "5 * 6 = 30")
        self.assertEqual(math_answer("20 divided by 4"), "20 / 4 = 5")
        self.assertEqual(math_answer("cuanto es 7 mas 8"), "7 + 8 = 15")

    def test_non_arithmetic(self):
        self.assertIsNone(math_answer("hello world"))
        self.assertIsNone(math_answer("what is the capital of france"))
        self.assertIsNone(math_answer("write a python function"))

    def test_division_by_zero(self):
        self.assertEqual(math_answer("10 divided by 0"), "division by zero is undefined")


class ThinkerLiteAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.layer = ThinkerLite()

    def test_math_intent(self):
        a = self.layer.analyze("what is 2 plus 3")
        self.assertEqual(a.intent, "math")
        self.assertEqual(a.math_result, "2 + 3 = 5")

    def test_identity_intent(self):
        a = self.layer.analyze("hello")
        self.assertEqual(a.intent, "identity")

    def test_recall_intent(self):
        a = self.layer.analyze("my name is alice")
        self.assertEqual(a.intent, "recall")
        self.assertEqual(a.expected_name, "alice")

    def test_code_intent(self):
        a = self.layer.analyze("write a python function")
        self.assertEqual(a.intent, "code")
        self.assertEqual(a.confidence, "low")

    def test_factual_intent(self):
        a = self.layer.analyze("what is the capital of france")
        self.assertEqual(a.intent, "factual")
        self.assertEqual(a.confidence, "low")

    def test_chat_intent(self):
        a = self.layer.analyze("tell me a story")
        self.assertEqual(a.intent, "chat")


class ThinkerLiteValidationTests(unittest.TestCase):
    def setUp(self):
        self.layer = ThinkerLite()

    def test_empty_reply_invalid(self):
        valid, notes = self.layer.validate("", self.layer.analyze("hello"))
        self.assertFalse(valid)
        self.assertIn("empty reply", notes)

    def test_filler_collapse_invalid(self):
        valid, notes = self.layer.validate("hello . . . .", self.layer.analyze("hi"))
        self.assertFalse(valid)
        self.assertIn("filler collapse detected", notes)

    def test_math_correct_pass(self):
        a = self.layer.analyze("what is 2 plus 3")
        valid, notes = self.layer.validate("2 + 3 = 5", a)
        self.assertTrue(valid)

    def test_math_wrong_fail(self):
        a = self.layer.analyze("what is 2 plus 3")
        valid, notes = self.layer.validate("the answer is 6", a)
        self.assertFalse(valid)
        self.assertIn("math answer does not match deterministic result", notes)

    def test_recall_correct_pass(self):
        a = self.layer.analyze("my name is bob")
        valid, notes = self.layer.validate("your name is bob", a)
        self.assertTrue(valid)

    def test_recall_missing_name_fail(self):
        a = self.layer.analyze("my name is charlie")
        valid, notes = self.layer.validate("i don't know", a)
        self.assertFalse(valid)
        self.assertIn("recall answer does not contain the expected name", notes)


class ThinkerLiteRepairTests(unittest.TestCase):
    def setUp(self):
        self.layer = ThinkerLite()

    def test_math_repair(self):
        a = self.layer.analyze("what is 5 times 4")
        repaired = self.layer.repair(a, "wrong answer")
        self.assertEqual(repaired, "5 * 4 = 20")

    def test_code_repair(self):
        a = self.layer.analyze("write a python script")
        repaired = self.layer.repair(a, "some code")
        self.assertIn("cannot reliably generate code", repaired)

    def test_factual_repair(self):
        a = self.layer.analyze("what is the population of china")
        repaired = self.layer.repair(a, "1.4 billion")
        self.assertIn("not certain about that", repaired)


class ApplyThinkerLiteTests(unittest.TestCase):
    def test_math_bypasses_llm(self):
        text, meta = apply_thinker_lite("what is 3 plus 4", "ignored")
        self.assertEqual(text, "3 + 4 = 7")
        self.assertEqual(meta["intent"], "math")
        self.assertTrue(meta["valid"])

    def test_regular_reply_validated(self):
        text, meta = apply_thinker_lite("hello", "hi there!")
        self.assertEqual(text, "hi there!")
        self.assertTrue(meta["valid"])

    def test_filler_triggers_repair(self):
        text, meta = apply_thinker_lite("hello", "hi . . . .")
        self.assertNotEqual(text, "hi . . . .")
        self.assertFalse(meta["valid"])
        # Check that repair was applied via steps
        repair_step = next((s for s in meta["steps"] if s["step"] == "repair"), None)
        self.assertIsNotNone(repair_step)
        self.assertEqual(repair_step["value"], "applied")

    def test_factual_decorates(self):
        text, meta = apply_thinker_lite("capital of france", "paris is the capital")
        self.assertTrue(text.startswith("i'm not certain, but"))


if __name__ == "__main__":
    unittest.main(verbosity=2)