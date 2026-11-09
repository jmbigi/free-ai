#!/usr/bin/env python3
import argparse, os, sys, time, shutil
from saga_core import Orchestrator, FaultPlan, SagaStatus

def _run_demo(data_dir, rid, oid, items, addr, fp, expected_status, print_dlq=False):
    orch = Orchestrator(data_dir=data_dir, fault_plan=fp, sleep_fn=lambda _: None)
    status = orch.run(rid, oid, 100.0, items, addr)
    sid = orch.st.db.query_one("SELECT saga_id FROM sagas WHERE request_id=?", (rid,))[0]
    print(f"request_id={rid} saga_id={sid} status={status.value}")
    for step, action, result, attempt, ts in orch.audit(sid):
        print(f" [{time.ctime(ts)}] {step} | {action} (a={attempt}) | {result}")
    if print_dlq:
        dlq = orch.st.dlq_list()
        if dlq:
            print("DLQ:")
            for s, step, err, ts in dlq:
                print(f" {s} | {step} | {err} | {time.ctime(ts)}")
    if status != expected_status:
        sys.exit(1)
    return orch, sid

def demo_happy(d): _run_demo(d, "req-happy", "order-1", ["item1"], "addr1", FaultPlan(), SagaStatus.COMPLETED)
def demo_payment_fail(d): _run_demo(d, "req-payment-fail", "order-2", ["item1"], "addr2", FaultPlan().fail("payment.reserve", 3, permanent=True), SagaStatus.COMPENSATED, True)
def demo_inventory_fail(d): _run_demo(d, "req-inventory-fail", "order-3", ["item1"], "addr3", FaultPlan().fail("inventory.reserve", 3, permanent=True), SagaStatus.COMPENSATED, True)
def demo_shipping_fail(d): _run_demo(d, "req-shipping-fail", "order-4", ["item1"], "addr4", FaultPlan().fail("shipping.create", 3, permanent=True), SagaStatus.COMPENSATED, True)
def demo_compensation_fail(d): _run_demo(d, "req-compensation-fail", "order-5", ["item1"], "addr5", FaultPlan().fail("shipping.create", 3, permanent=True).fail("inventory.release", 3, permanent=True), SagaStatus.MANUAL_INTERVENTION, True)
def demo_retry_success(d): _run_demo(d, "req-retry-success", "order-6", ["item1"], "addr6", FaultPlan().fail("inventory.reserve", 1), SagaStatus.COMPLETED)

def demo_crash_recovery(d):
    fp = FaultPlan().crash_after("payment.reserve")
    orch1 = Orchestrator(data_dir=d, fault_plan=fp, sleep_fn=lambda _: None)
    rid = "req-crash-recovery"
    status1 = orch1.run(rid, "order-7", 100.0, ["item1"], "addr7")
    sid = orch1.st.db.query_one("SELECT saga_id FROM sagas WHERE request_id=?", (rid,))[0]
    print(f"request_id={rid} saga_id={sid} status={status1.value}")
    for step, action, result, attempt, ts in orch1.audit(sid):
        print(f" [{time.ctime(ts)}] {step} | {action} (a={attempt}) | {result}")
    if status1 != SagaStatus.RUNNING: sys.exit(1)
    print("--- Recovery ---")
    orch2 = Orchestrator(data_dir=d, sleep_fn=lambda _: None)
    recovered = orch2.recover(force=True)
    print(f"Recovered: {recovered}")
    status2 = orch2._status(sid)
    print(f"After recovery: {status2.value}")
    for step, action, result, attempt, ts in orch2.audit(sid):
        print(f" [{time.ctime(ts)}] {step} | {action} (a={attempt}) | {result}")
    if status2 != SagaStatus.COMPLETED: sys.exit(1)

def demo_duplicate(d):
    orch = Orchestrator(data_dir=d, sleep_fn=lambda _: None)
    rid = "req-duplicate"
    s1 = orch.run(rid, "order-8", 100.0, ["item1"], "addr8")
    s2 = orch.run(rid, "order-8", 100.0, ["item1"], "addr8")
    sid = orch.st.db.query_one("SELECT saga_id FROM sagas WHERE request_id=?", (rid,))[0]
    print(f"request_id={rid} saga_id={sid} status1={s1.value} status2={s2.value}")
    for step, action, result, attempt, ts in orch.audit(sid):
        print(f" [{time.ctime(ts)}] {step} | {action} (a={attempt}) | {result}")
    total = 0
    for svc in ["payment", "inventory", "shipping"]:
        db_path = os.path.join(d, f"{svc}.db")
        import sqlite3
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM effects WHERE k LIKE ?", (f"{sid}:%",)).fetchone()[0]
        conn.close()
        total += count
    print(f"Total effects: {total} (expected 3)")
    if total != 3: sys.exit(1)

def demo_concurrent(d):
    orch = Orchestrator(data_dir=d, sleep_fn=lambda _: None)
    rids = [f"req-concurrent-{i}" for i in range(8)]
    results = orch.run_many(rids, workers=4)
    ok = True
    for rid, status in results.items():
        sid = orch.st.db.query_one("SELECT saga_id FROM sagas WHERE request_id=?", (rid,))[0]
        print(f"request_id={rid} saga_id={sid} status={status.value}")
        if status != SagaStatus.COMPLETED: ok = False
    if not ok: sys.exit(1)

def run_demo(scenario, data_dir):
    demos = {"happy": demo_happy, "payment_fail": demo_payment_fail, "inventory_fail": demo_inventory_fail,
             "shipping_fail": demo_shipping_fail, "compensation_fail": demo_compensation_fail,
             "retry_success": demo_retry_success, "crash_recovery": demo_crash_recovery,
             "duplicate": demo_duplicate, "concurrent": demo_concurrent}
    if scenario not in demos: print(f"Unknown: {scenario}"); sys.exit(1)
    demo_dir = os.path.join(data_dir, f"demo_{scenario}")
    if os.path.exists(demo_dir): shutil.rmtree(demo_dir)
    demos[scenario](demo_dir)

def run_audit(sid, data_dir):
    for step, action, result, attempt, ts in Orchestrator(data_dir=data_dir).audit(sid):
        print(f" [{time.ctime(ts)}] {step} | {action} (a={attempt}) | {result}")

def run_dlq(data_dir):
    for s, step, err, ts in Orchestrator(data_dir=data_dir).st.dlq_list():
        print(f"{s} | {step} | {err} | {time.ctime(ts)}")

def run_recover(force, data_dir):
    print(f"Recovered: {Orchestrator(data_dir=data_dir).recover(force=force)}")

def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    dp = sp.add_parser("demo")
    dp.add_argument("--scenario", required=True, choices=list({"happy", "payment_fail", "inventory_fail", "shipping_fail",
             "compensation_fail", "retry_success", "crash_recovery", "duplicate", "concurrent"}))
    dp.add_argument("--data-dir", default=os.environ.get("SAGA_DATA_DIR", "data"))
    ap_audit = sp.add_parser("audit")
    ap_audit.add_argument("saga_id")
    ap_audit.add_argument("--data-dir", default=os.environ.get("SAGA_DATA_DIR", "data"))
    sp.add_parser("dlq").add_argument("--data-dir", default=os.environ.get("SAGA_DATA_DIR", "data"))
    rec = sp.add_parser("recover")
    rec.add_argument("--force", action="store_true")
    rec.add_argument("--data-dir", default=os.environ.get("SAGA_DATA_DIR", "data"))
    a = ap.parse_args()
    if a.cmd == "demo": run_demo(a.scenario, a.data_dir)
    elif a.cmd == "audit": run_audit(a.saga_id, a.data_dir)
    elif a.cmd == "dlq": run_dlq(a.data_dir)
    elif a.cmd == "recover": run_recover(a.force, a.data_dir)

if __name__ == "__main__": main()