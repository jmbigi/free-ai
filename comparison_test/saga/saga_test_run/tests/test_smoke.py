import unittest
import tempfile
import sqlite3
import os
from unittest.mock import patch

from saga_core import Orchestrator, FaultPlan, SagaStatus  # Asegúrate de reemplazar 'your_module' con el nombre real del módulo

def db(d): return sqlite3.connect(os.path.join(d, "saga.db"))

class TestSmoke(unittest.TestCase):
    def test_happy(self):
        with tempfile.TemporaryDirectory() as d:
            orch = Orchestrator(data_dir=d, fault_plan=FaultPlan())
            status = orch.run("req1", "order1", 100.0, ["item"], {"addr": "x"})
            self.assertEqual(status, SagaStatus.COMPLETED)
            row = orch.store.get_by_request("req1")
            sid = row["saga_id"]

            conn = db(d)
            events = list(conn.execute("SELECT * FROM events WHERE saga_id=?", (sid,)))
            self.assertEqual(len(events), 3)
            self.assertTrue(all(e[3] == 'fwd' for e in events))

            effects = list(conn.execute("SELECT key FROM effects WHERE key LIKE ?", (sid + ":%",)))
            self.assertEqual(len(effects), 3)
            self.assertTrue(all(e[0].startswith(sid + ":") for e in effects))

    def test_inventory_fail(self):
        with tempfile.TemporaryDirectory() as d:
            fp = FaultPlan().fail("inventory.reserve", 3, permanent=True)
            orch = Orchestrator(data_dir=d, fault_plan=fp)
            status = orch.run("req1", "order1", 100.0, ["item"], {"addr": "x"})
            self.assertEqual(status, SagaStatus.COMPENSATED)

            row = orch.store.get_by_request("req1")
            sid = row["saga_id"]

            conn = db(d)
            dlq = list(conn.execute("SELECT * FROM dlq WHERE saga_id=?", (sid,)))
            self.assertTrue(any("inventory.reserve" in str(row) for row in dlq))

            effects = list(conn.execute("SELECT key FROM effects WHERE key LIKE ?", (sid + ":%",)))
            effect_keys = [e[0] for e in effects]
            self.assertTrue(any(k.startswith(sid + ":payment") and "reserve" in k for k in effect_keys))
            self.assertTrue(any(k.startswith(sid + ":payment") and "refund" in k for k in effect_keys))

    def test_retry(self):
        with tempfile.TemporaryDirectory() as d:
            fp = FaultPlan().fail("inventory.reserve", 1)
            orch = Orchestrator(data_dir=d, fault_plan=fp)
            status = orch.run("req1", "order1", 100.0, ["item"], {"addr": "x"})
            self.assertEqual(status, SagaStatus.COMPLETED)

            row = orch.store.get_by_request("req1")
            sid = row["saga_id"]

            conn = db(d)
            events = list(conn.execute("SELECT * FROM events WHERE saga_id=?", (sid,)))
            self.assertEqual(len(events), 4)  # 3 fwd + 1 fail
            self.assertEqual(events[0][3], 'fwd')
            self.assertEqual(events[1][3], 'fail')
            self.assertEqual(events[2][3], 'fwd')

            effects = list(conn.execute("SELECT key FROM effects WHERE key LIKE ?", (sid + ":%",)))
            effect_keys = [e[0] for e in effects]
            inventory_effects = [k for k in effect_keys if k.startswith(sid + ":inventory")]
            self.assertEqual(len(inventory_effects), 1)

    def test_crash_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            fp = FaultPlan().crash_after("payment.reserve")
            orch = Orchestrator(data_dir=d, fault_plan=fp)
            status = orch.run("req1", "order1", 100.0, ["item"], {"addr": "x"})
            self.assertEqual(status, SagaStatus.RUNNING)

            row = orch.store.get_by_request("req1")
            sid = row["saga_id"]

            orch2 = Orchestrator(data_dir=d, fault_plan=FaultPlan())
            orch2.recover(force=True)
            status2 = orch2.run("req1", "order1", 100.0, ["item"], {"addr": "x"})
            self.assertEqual(status2, SagaStatus.COMPLETED)

            conn = db(d)
            effects = list(conn.execute("SELECT key FROM effects WHERE key LIKE ?", (sid + ":%",)))
            effect_keys = [e[0] for e in effects]
            payment_effects = [k for k in effect_keys if k.startswith(sid + ":payment")]
            self.assertEqual(len(payment_effects), 1)

    def test_run_many(self):
        with tempfile.TemporaryDirectory() as d:
            orch = Orchestrator(data_dir=d, fault_plan=FaultPlan())
            orch.run_many(["r1","r2","r3","r4"], workers=2)

            conn = db(d)
            for req_id in ["r1","r2","r3","r4"]:
                row = orch.store.get_by_request(req_id)
                sid = row["saga_id"]
                effects = list(conn.execute("SELECT key FROM effects WHERE key LIKE ?", (sid + ":%",)))
                self.assertEqual(len(effects), 3)


