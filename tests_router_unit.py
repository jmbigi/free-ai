"""Deterministic unit tests for fallback policy (no upstream network calls).

Run: .venv/bin/python -m unittest tests_router_unit.py -v
"""
from __future__ import annotations

import asyncio
import time
import unittest
from collections import Counter

from app.providers.base import ProviderError, parse_retry_after
from app.router import (
    _RATE_LAST,
    _RATE_LOCKS,
    _breaker_failure,
    _breaker_left,
    _breaker_open,
    _breaker_success,
    _build_auto_plan,
    _classify_failure,
    _throttle,
)


class FailureClassificationTests(unittest.TestCase):
    def test_provider_wide_faults(self):
        for status in (401, 403, 402, 429):
            self.assertEqual(_classify_failure(ProviderError("x", status=status)), "provider", status)

    def test_model_and_terminal_and_transient(self):
        self.assertEqual(_classify_failure(ProviderError("model not found", status=404)), "model")
        self.assertEqual(_classify_failure(ProviderError("invalid request body", status=400)), "terminal")
        self.assertEqual(_classify_failure(ProviderError("upstream failed", status=500)), "transient")
        self.assertEqual(_classify_failure(ProviderError("invalid api key", status=502)), "provider")

    def test_timeout_is_transient(self):
        self.assertEqual(_classify_failure(asyncio.TimeoutError()), "transient")


class RetryAfterTests(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(parse_retry_after("12"), 12.0)
        self.assertEqual(parse_retry_after("0"), 0.0)

    def test_invalid(self):
        self.assertIsNone(parse_retry_after("not-a-date"))
        self.assertIsNone(parse_retry_after(None))


class BreakerTests(unittest.TestCase):
    def tearDown(self):
        for pid in ("unit-provider", "unit-auth", "unit-transient"):
            _breaker_success(pid)

    def test_quota_opens_immediately_and_honors_retry_after(self):
        _breaker_failure("unit-provider", "provider",
                         ProviderError("quota", status=429, retry_after=46))
        self.assertTrue(_breaker_open("unit-provider"))
        self.assertGreaterEqual(_breaker_left("unit-provider"), 45)

    def test_auth_opens_for_at_least_five_minutes(self):
        _breaker_failure("unit-auth", "provider", ProviderError("bad key", status=401))
        self.assertGreaterEqual(_breaker_left("unit-auth"), 299)

    def test_transient_opens_after_threshold(self):
        for _ in range(2):
            _breaker_failure("unit-transient", "transient", ProviderError("500", status=500))
        self.assertFalse(_breaker_open("unit-transient"))
        _breaker_failure("unit-transient", "transient", ProviderError("500", status=503))
        self.assertTrue(_breaker_open("unit-transient"))

    def test_success_resets(self):
        _breaker_failure("unit-provider", "provider", ProviderError("quota", status=429))
        _breaker_success("unit-provider")
        self.assertFalse(_breaker_open("unit-provider"))


class PlanTests(unittest.TestCase):
    def tearDown(self):
        _breaker_success("llm7")

    def test_plan_caps_models_per_provider(self):
        plan = _build_auto_plan(exclude=set(), max_items=50)
        per_provider = Counter(provider.id for provider, _ in plan)
        self.assertTrue(plan)
        for pid, count in per_provider.items():
            self.assertLessEqual(count, 2, f"{pid} contributed {count} models")

    def test_plan_skips_open_breaker(self):
        _breaker_failure("llm7", "provider", ProviderError("quota", status=429, retry_after=60))
        plan = _build_auto_plan(exclude=set(), max_items=50)
        self.assertNotIn("llm7", {provider.id for provider, _ in plan})
        self.assertTrue(all(not _breaker_open(provider.id) for provider, _ in plan))

    def test_local_models_are_free_for_policy(self):
        from app.router import is_free_model
        self.assertTrue(is_free_model({"id": "ncm/ncm-instruct-725m", "provider": "ncm"}))
        self.assertTrue(is_free_model({"id": "local-ollama/qwen3.5:9b-q4_K_M", "provider": "local-ollama"}))
        self.assertTrue(is_free_model({"id": "ncm-lm1b/ncm-lm1b-large", "provider": "ncm-lm1b"}))

    def test_plan_allowlist_restricts_providers(self):
        from app.config import settings
        candidates = [p for p, enabled in (
            ("local-ollama", settings.local_ollama_enabled),
            ("ncm", settings.ncm_local_enabled),
        ) if enabled]
        if not candidates:
            self.skipTest("no local auto-fallback provider enabled")
        target = candidates[0]
        plan = _build_auto_plan(exclude=set(), max_items=10, allowed_providers={target})
        self.assertTrue(plan)
        self.assertEqual({provider.id for provider, _ in plan}, {target})

    def test_plan_keeps_local_fallback_before_second_models(self):
        from app.config import settings
        target = "local-ollama" if settings.local_ollama_enabled else None
        if not target:
            self.skipTest("local Ollama fallback disabled")
        plan = _build_auto_plan(exclude=set(), max_items=50)
        ids = [provider.id for provider, _ in plan]
        self.assertIn(target, ids)
        self.assertEqual(ids.count(target), 1, ids)
        idx = ids.index(target)
        self.assertEqual(len(ids[:idx]), len(set(ids[:idx])), ids)

    def test_plan_keeps_local_ncm_before_second_models(self):
        from app.config import settings
        if not settings.ncm_local_enabled:
            self.skipTest("NCM local fallback disabled")
        plan = _build_auto_plan(exclude=set(), max_items=50)
        ids = [provider.id for provider, _ in plan]
        self.assertIn("ncm", ids)
        self.assertEqual(ids.count("ncm"), 1, ids)
        ncm_idx = ids.index("ncm")
        # No provider may be retried before the local fallback is tried.
        self.assertEqual(len(ids[:ncm_idx]), len(set(ids[:ncm_idx])), ids)


class ThrottleTests(unittest.TestCase):
    def test_throttle_fails_fast_instead_of_sleeping_past_budget(self):
        async def scenario():
            _RATE_LAST["pollinations"] = time.time()
            started = time.time()
            with self.assertRaises(ProviderError) as ctx:
                await _throttle("pollinations", deadline=time.time() + 5)
            elapsed = time.time() - started
            self.assertLess(elapsed, 0.5)
            self.assertEqual(ctx.exception.status, 429)
            self.assertGreater(ctx.exception.retry_after or 0, 40)

        asyncio.run(scenario())

    def test_throttle_lock_contention_fails_fast(self):
        async def scenario():
            _RATE_LAST["pollinations"] = 0.0
            lock = _RATE_LOCKS.setdefault("pollinations", asyncio.Lock())
            await lock.acquire()
            try:
                started = time.time()
                with self.assertRaises(ProviderError):
                    await _throttle("pollinations", deadline=time.time() + 0.2)
                self.assertLess(time.time() - started, 1.0)
            finally:
                lock.release()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
