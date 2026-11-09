import unittest
import tempfile
import sqlite3
import json
from saga_core import Orchestrator, FaultPlan, SagaStatus, EffectStore, Store


class TestSaga(unittest.TestCase):
    def _mk_orch(self, fp=None):
        return Orchestrator(data_dir=self.tmpdir, fault_plan=fp, sleep_fn=lambda _: None)

    def _count_effects(self, svc, key_prefix):
        db = sqlite3.connect(f"{self.tmpdir}/{svc}.db")
        r = db.execute("SELECT COUNT(*) FROM effects WHERE k LIKE ?", (f"{key_prefix}%",)).fetchone()[0]
        db.close()
        return r

    def _get_events(self, saga_id, action=None):
        db = sqlite3.connect(f"{self.tmpdir}/orchestrator.db")
        q = "SELECT step,action,result,attempt FROM events WHERE saga_id=?"
        params = (saga_id,)
        if action:
            q += " AND action=?"
            params += (action,)
        q += " ORDER BY id"
        r = db.execute(q, params).fetchall()
        db.close()
        return r

    def _get_dlq(self, saga_id=None):
        db = sqlite3.connect(f"{self.tmpdir}/orchestrator.db")
        if saga_id:
            r = db.execute("SELECT step,error FROM dlq WHERE saga_id=?", (saga_id,)).fetchall()
        else:
            r = db.execute("SELECT saga_id,step,error FROM dlq ORDER BY id").fetchall()
        db.close()
        return r

    def _get_saga_status(self, saga_id):
        db = sqlite3.connect(f"{self.tmpdir}/orchestrator.db")
        r = db.execute("SELECT status FROM sagas WHERE saga_id=?", (saga_id,)).fetchone()
        db.close()
        return SagaStatus(r[0]) if r else None

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory().name
        import os
        os.makedirs(self.tmpdir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_1_happy_path(self):
        orch = self._mk_orch()
        status = orch.run("req-1", "order-1", 100.0, ["item1"], "addr1")
        self.assertEqual(status, SagaStatus.COMPLETED)

        saga_id = self._get_saga_id("req-1")
        fwd = self._get_events(saga_id, "fwd")
        self.assertEqual(len(fwd), 3)
        steps = [e[0] for e in fwd]
        self.assertEqual(steps, ["payment.reserve", "inventory.reserve", "shipping.create"])

        for svc in ["payment", "inventory", "shipping"]:
            self.assertEqual(self._count_effects(svc, f"{saga_id}:"), 1)

    def test_2_payment_permanent_fail(self):
        fp = FaultPlan().fail("payment.reserve", 3, permanent=True)
        orch = self._mk_orch(fp)
        status = orch.run("req-2", "order-2", 100.0, ["item1"], "addr2")
        self.assertIn(status, (SagaStatus.COMPENSATED, SagaStatus.FAILED))

        saga_id = self._get_saga_id("req-2")
        self.assertEqual(self._count_effects("inventory", f"{saga_id}:"), 0)
        self.assertEqual(self._count_effects("shipping", f"{saga_id}:"), 0)
        dlq = self._get_dlq(saga_id)
        self.assertTrue(any("payment.reserve" in d[0] for d in dlq))

    def test_3_inventory_fail_after_payment(self):
        fp = FaultPlan().fail("inventory.reserve", 3, permanent=True)
        orch = self._mk_orch(fp)
        status = orch.run("req-3", "order-3", 100.0, ["item1"], "addr3")
        self.assertEqual(status, SagaStatus.COMPENSATED)

        saga_id = self._get_saga_id("req-3")
        self.assertEqual(self._count_effects("payment", f"{saga_id}:"), 2)
        self.assertEqual(self._count_effects("inventory", f"{saga_id}:"), 0)
        dlq = self._get_dlq(saga_id)
        self.assertTrue(any("inventory.reserve" in d[0] for d in dlq))

    def test_4_shipping_fail_after_payment_inventory(self):
        fp = FaultPlan().fail("shipping.create", 3, permanent=True)
        orch = self._mk_orch(fp)
        status = orch.run("req-4", "order-4", 100.0, ["item1"], "addr4")
        self.assertEqual(status, SagaStatus.COMPENSATED)

        saga_id = self._get_saga_id("req-4")
        self.assertEqual(self._count_effects("shipping", f"{saga_id}:"), 0)
        self.assertEqual(self._count_effects("inventory", f"{saga_id}:"), 2)
        self.assertEqual(self._count_effects("payment", f"{saga_id}:"), 2)
        dlq = self._get_dlq(saga_id)
        self.assertTrue(any("shipping.create" in d[0] for d in dlq))

    def test_5_compensation_failure(self):
        fp = FaultPlan().fail("shipping.create", 3, permanent=True).fail("inventory.release", 3, permanent=True)
        orch = self._mk_orch(fp)
        status = orch.run("req-5", "order-5", 100.0, ["item1"], "addr5")
        self.assertEqual(status, SagaStatus.MANUAL_INTERVENTION)

        saga_id = self._get_saga_id("req-5")
        dlq = self._get_dlq(saga_id)
        self.assertTrue(any("inventory.release" in d[0] for d in dlq))

    def test_6_retry(self):
        fp = FaultPlan().fail("inventory.reserve", 1)
        orch = self._mk_orch(fp)
        status = orch.run("req-6", "order-6", 100.0, ["item1"], "addr6")
        self.assertEqual(status, SagaStatus.COMPLETED)

        saga_id = self._get_saga_id("req-6")
        self.assertEqual(self._count_effects("inventory", f"{saga_id}:"), 1)
        ev = self._get_events(saga_id)
        inv_events = [e for e in ev if e[0] == "inventory.reserve"]
        attempts = [e[3] for e in inv_events]
        self.assertIn(1, attempts)
        self.assertIn(2, attempts)

    def test_7_crash_recovery(self):
        fp = FaultPlan().crash_after("payment.reserve")
        orch1 = self._mk_orch(fp)
        status1 = orch1.run("req-7", "order-7", 100.0, ["item1"], "addr7")
        self.assertEqual(status1, SagaStatus.RUNNING)

        saga_id = self._get_saga_id("req-7")
        self.assertEqual(self._count_effects("payment", f"{saga_id}:"), 1)

        orch2 = self._mk_orch()
        orch2.recover(force=True)
        status2 = self._get_saga_status(saga_id)
        self.assertEqual(status2, SagaStatus.COMPLETED)
        self.assertEqual(self._count_effects("payment", f"{saga_id}:"), 1)

    def test_8_idempotent_request_id(self):
        orch = self._mk_orch()
        orch.run("req-8", "order-8", 100.0, ["item1"], "addr8")
        orch.run("req-8", "order-8", 100.0, ["item1"], "addr8")

        saga_id = self._get_saga_id("req-8")
        total_effects = sum(self._count_effects(svc, f"{saga_id}:") for svc in ["payment", "inventory", "shipping"])
        self.assertEqual(total_effects, 3)

    def test_9_idempotent_service_call(self):
        es = EffectStore(self.tmpdir, "payment")
        k = "same-key"
        r1 = es.exec(k, lambda: "result1")
        r2 = es.exec(k, lambda: "result2")
        self.assertEqual(r1, r2)
        self.assertEqual(r1, "result1")
        db = sqlite3.connect(f"{self.tmpdir}/payment.db")
        cnt = db.execute("SELECT COUNT(*) FROM effects WHERE k=?", (k,)).fetchone()[0]
        db.close()
        self.assertEqual(cnt, 1)

    def test_10_concurrency(self):
        orch = self._mk_orch()
        rids = [f"req-{i}" for i in range(10)]
        results = orch.run_many(rids, workers=4)
        self.assertEqual(len(results), 10)
        for rid, st in results.items():
            self.assertEqual(st, SagaStatus.COMPLETED)

        for rid in rids:
            saga_id = self._get_saga_id(rid)
            fwd = self._get_events(saga_id, "fwd")
            self.assertEqual(len(fwd), 3)
            total = sum(self._count_effects(svc, f"{saga_id}:") for svc in ["payment", "inventory", "shipping"])
            self.assertEqual(total, 3)

    def test_11_audit_invariants(self):
        orch = self._mk_orch()
        orch.run("req-11a", "order-11a", 100.0, ["item1"], "addr11a")
        saga_id = self._get_saga_id("req-11a")
        ev = self._get_events(saga_id)
        fwd_steps = [e[0] for e in ev if e[1] == "fwd"]
        self.assertEqual(set(fwd_steps), {"payment.reserve", "inventory.reserve", "shipping.create"})

        fp = FaultPlan().fail("shipping.create", 3, permanent=True)
        orch2 = self._mk_orch(fp)
        orch2.run("req-11b", "order-11b", 100.0, ["item1"], "addr11b")
        saga_id2 = self._get_saga_id("req-11b")
        ev2 = self._get_events(saga_id2)
        comp_steps = [e[0] for e in ev2 if e[1] == "comp"]
        self.assertTrue(any("refund" in s or "release" in s or "cancel" in s for s in comp_steps))

        dlq = self._get_dlq()
        completed_sagas = set()
        db = sqlite3.connect(f"{self.tmpdir}/orchestrator.db")
        for row in db.execute("SELECT saga_id FROM sagas WHERE status=?", (SagaStatus.COMPLETED.value,)):
            completed_sagas.add(row[0])
        db.close()
        for d in dlq:
            self.assertNotIn(d[0], completed_sagas)

    def _get_saga_id(self, request_id):
        db = sqlite3.connect(f"{self.tmpdir}/orchestrator.db")
        r = db.execute("SELECT saga_id FROM sagas WHERE request_id=?", (request_id,)).fetchone()
        db.close()
        return r[0] if r else None


if __name__ == "__main__":
    unittest.main()