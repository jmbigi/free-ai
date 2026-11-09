import os, sqlite3, threading, time, uuid, json
from enum import Enum
from typing import Callable, List, Tuple, Any, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

SAGA_DATA_DIR = os.environ.get("SAGA_DATA_DIR", "data")

class SagaStatus(Enum): PENDING="PENDING"; RUNNING="RUNNING"; COMPLETED="COMPLETED"; COMPENSATING="COMPENSATING"; COMPENSATED="COMPENSATED"; FAILED="FAILED"; MANUAL_INTERVENTION="MANUAL_INTERVENTION"
class _Crash(Exception):
    """Señal interna para simular una caída sin compensar."""

class FaultPlan:
 def __init__(self): self._f = {}; self._crash = None
 def fail(self, step: str, times: int, permanent=False): self._f[step] = (times, permanent); return self
 def crash_after(self, step: str): self._crash = step; return self
 def should_fail(self, step: str, attempt: int) -> bool:
  if step in self._f:
   t, p = self._f[step]
   if p or attempt <= t: return True
  return False
 def should_crash(self, step: str) -> bool: return self._crash == step

class _ThreadLocalStore:
 def __init__(self, path: str): self.path = path; self.local = threading.local()
 def _conn(self) -> sqlite3.Connection:
  c = getattr(self.local, 'conn', None)
  if c is None:
   c = sqlite3.connect(self.path, check_same_thread=False)
   c.execute("PRAGMA journal_mode=WAL"); self.local.conn = c
  return c
 def exec(self, sql: str, params: tuple = ()): c = self._conn(); c.execute(sql, params); c.commit()
 def query(self, sql: str, params: tuple = ()): c = self._conn(); return c.execute(sql, params).fetchall()
 def query_one(self, sql: str, params: tuple = ()): c = self._conn(); return c.execute(sql, params).fetchone()

class Store:
 def __init__(self, d: str):
  os.makedirs(d, exist_ok=True)
  self.db = _ThreadLocalStore(os.path.join(d, "orchestrator.db"))
  self.db.exec("""CREATE TABLE IF NOT EXISTS sagas(
   request_id TEXT UNIQUE, saga_id TEXT PRIMARY KEY, status TEXT, current_step TEXT,
   lease_until REAL, order_id TEXT, amount REAL, items TEXT, address TEXT
  )""")
  self.db.exec("""CREATE TABLE IF NOT EXISTS events(
   id INTEGER PRIMARY KEY, saga_id TEXT, step TEXT, action TEXT, result TEXT, attempt INTEGER, ts REAL
  )""")
  self.db.exec("""CREATE TABLE IF NOT EXISTS dlq(
   id INTEGER PRIMARY KEY, saga_id TEXT, step TEXT, error TEXT, ts REAL
  )""")
 def create_or_get(self, rid: str, oid: str, amt: float, items: list, addr: str) -> Tuple[str, SagaStatus]:
  r = self.db.query_one("SELECT saga_id,status FROM sagas WHERE request_id=?", (rid,))
  if r: return r[0], SagaStatus(r[1])
  sid = str(uuid.uuid4())
  self.db.exec("INSERT INTO sagas VALUES(?,?,?,?,?,?,?,?,?)",
   (rid, sid, SagaStatus.PENDING.value, "", 0, oid, amt, json.dumps(items), addr))
  return sid, SagaStatus.PENDING
 def set_status(self, sid: str, st: SagaStatus, step: str = "", lease: float = 0):
  self.db.exec("UPDATE sagas SET status=?,current_step=?,lease_until=? WHERE saga_id=?",
   (st.value, step, lease, sid))
 def event(self, sid: str, step: str, act: str, res: str, attempt: int = 1):
  self.db.exec("INSERT INTO events(saga_id,step,action,result,attempt,ts) VALUES(?,?,?,?,?,?)",
   (sid, step, act, res, attempt, time.time()))
 def audit(self, sid: str) -> List[Tuple]:
  return self.db.query("SELECT step,action,result,attempt,ts FROM events WHERE saga_id=? ORDER BY id", (sid,))
 def dlq_add(self, sid: str, step: str, err: str):
  self.db.exec("INSERT INTO dlq(saga_id,step,error,ts) VALUES(?,?,?,?)", (sid, step, err, time.time()))
 def dlq_list(self) -> List[Tuple]:
  return self.db.query("SELECT saga_id,step,error,ts FROM dlq ORDER BY id")
 def get_saga(self, sid: str):
  return self.db.query_one("SELECT request_id,saga_id,status,current_step,lease_until,order_id,amount,items,address FROM sagas WHERE saga_id=?", (sid,))
 def get_pending(self):
  return self.db.query("SELECT saga_id,status,current_step,lease_until FROM sagas WHERE status IN (?,?)",
  (SagaStatus.PENDING.value, SagaStatus.RUNNING.value))
 def claim(self, sid: str, lease: float = 30, force: bool = False) -> bool:
  now = time.time(); c = self.db._conn(); c.execute("BEGIN IMMEDIATE")
  try:
   if force:
    r = c.execute("UPDATE sagas SET status=?,lease_until=? WHERE saga_id=? AND status IN (?,?)",
                  (SagaStatus.RUNNING.value, now + lease, sid, SagaStatus.PENDING.value, SagaStatus.RUNNING.value))
   else:
    r = c.execute("UPDATE sagas SET status=?,lease_until=? WHERE saga_id=? AND (status=? OR (status=? AND (lease_until=0 OR lease_until<?)))",
                  (SagaStatus.RUNNING.value, now + lease, sid, SagaStatus.PENDING.value, SagaStatus.RUNNING.value, now))
   c.commit(); return r.rowcount > 0
  except Exception:
   c.rollback(); return False
class EffectStore:
 def __init__(self, d: str, n: str):
  self.db = _ThreadLocalStore(os.path.join(d, f"{n}.db"))
  self.db.exec("CREATE TABLE IF NOT EXISTS effects(k TEXT PRIMARY KEY, v TEXT)")
 def exec(self, k: str, fn: Callable[[], Any]) -> Any:
  c = self.db._conn(); c.execute("BEGIN IMMEDIATE")
  try:
   r = c.execute("SELECT v FROM effects WHERE k=?", (k,)).fetchone()
   if r: c.commit(); return r[0]
   v = fn(); c.execute("INSERT INTO effects VALUES(?,?)", (k, str(v))); c.commit(); return v
  except sqlite3.IntegrityError:
   c.rollback(); r = c.execute("SELECT v FROM effects WHERE k=?", (k,)).fetchone(); return r[0] if r else None
  except Exception:
   c.rollback(); raise

class PaymentService:
 def __init__(self, d): self.s = EffectStore(d, "payment")
 def reserve(self, sid, oid, amt): return self.s.exec(f"{sid}:payment.reserve", lambda: f"reserved:{oid}:{amt}")
 def refund(self, sid, r): return self.s.exec(f"{sid}:payment.refund", lambda: f"refunded:{r}")

class InventoryService:
 def __init__(self, d): self.s = EffectStore(d, "inventory")
 def reserve(self, sid, oid, items): return self.s.exec(f"{sid}:inventory.reserve", lambda: f"reserved:{oid}:{','.join(items)}")
 def release(self, sid, r): return self.s.exec(f"{sid}:inventory.release", lambda: f"released:{r}")

class ShippingService:
 def __init__(self, d): self.s = EffectStore(d, "shipping")
 def create(self, sid, oid, addr): return self.s.exec(f"{sid}:shipping.create", lambda: f"created:{oid}:{addr}")
 def cancel(self, sid, s): return self.s.exec(f"{sid}:shipping.cancel", lambda: f"cancelled:{s}")

class Orchestrator:
 STEPS = [
  ("payment.reserve", lambda s, o, sid: s.payment.reserve(sid, o.oid, o.amt)),
  ("inventory.reserve", lambda s, o, sid: s.inventory.reserve(sid, o.oid, o.items)),
  ("shipping.create", lambda s, o, sid: s.shipping.create(sid, o.oid, o.addr))
 ]
 COMP = [
  ("payment.refund", lambda s, r, sid: s.payment.refund(sid, r)),
  ("inventory.release", lambda s, r, sid: s.inventory.release(sid, r)),
  ("shipping.cancel", lambda s, r, sid: s.shipping.cancel(sid, r))
 ]
 def __init__(self, data_dir=SAGA_DATA_DIR, fault_plan=None, max_attempts=3, sleep_fn=None):
  self.d = data_dir; self.fp = fault_plan or FaultPlan(); self.ma = max_attempts; self.sf = sleep_fn or time.sleep
  self.st = Store(data_dir); self.payment = PaymentService(data_dir)
  self.inventory = InventoryService(data_dir); self.shipping = ShippingService(data_dir)

 def run(self, rid: str, oid: str, amt: float, items: list, addr: str) -> SagaStatus:
  sid, st = self.st.create_or_get(rid, oid, amt, items, addr)
  if st in (SagaStatus.COMPLETED, SagaStatus.COMPENSATED, SagaStatus.MANUAL_INTERVENTION, SagaStatus.FAILED):
   return st
  if not self.st.claim(sid): return self._status(sid)
  o = type('O', (), {'oid': oid, 'amt': amt, 'items': items, 'addr': addr})()
  done = []
  try:
   for name, fn in self.STEPS:
    self.st.set_status(sid, SagaStatus.RUNNING, name, time.time() + 30)
    for a in range(1, self.ma + 1):
     if self.fp.should_fail(name, a):
      self.st.event(sid, name, "fail", "", a)
      if a == self.ma:
       self.st.dlq_add(sid, name, f"{name} failed after {a} attempts")
       raise Exception(f"{name} failed")
      self.sf(0.01); continue
     try:
      res = fn(self, o, sid); done.append((name, res)); self.st.event(sid, name, "fwd", res, a); break
     except Exception as e:
      self.st.event(sid, name, "fail", str(e), a)
      if a == self.ma:
       self.st.dlq_add(sid, name, str(e)); raise
      self.sf(0.01)
    if self.fp.should_crash(name):
     self.st.set_status(sid, SagaStatus.RUNNING, name, 0); raise _Crash(f"crash after {name}")
   self.st.set_status(sid, SagaStatus.COMPLETED, "", 0); return SagaStatus.COMPLETED
  except _Crash:
   return SagaStatus.RUNNING
  except Exception as e: return self._comp(sid, done, str(e), failed_step=name)

 def _comp(self, sid: str, done: List[Tuple], err: str, failed_step: str = "") -> SagaStatus:
  self.st.set_status(sid, SagaStatus.COMPENSATING, "comp", time.time() + 30)
  for name, res in reversed(done):
   ci = next(i for i, (n, _) in enumerate(self.STEPS) if n == name)
   cname, cfn = self.COMP[ci]
   for a in range(1, self.ma + 1):
    if self.fp.should_fail(cname, a):
     if a == self.ma:
      self.st.dlq_add(sid, cname, f"{cname} compensation failed after {a} attempts")
      self.st.set_status(sid, SagaStatus.MANUAL_INTERVENTION, cname, 0); return SagaStatus.MANUAL_INTERVENTION
     self.sf(0.01); continue
    try: cres = cfn(self, res, sid); self.st.event(sid, cname, "comp", cres, a); break
    except Exception as ce:
     if a == self.ma:
      self.st.dlq_add(sid, cname, str(ce))
      self.st.set_status(sid, SagaStatus.MANUAL_INTERVENTION, cname, 0); return SagaStatus.MANUAL_INTERVENTION
     self.sf(0.01)
  step = failed_step or "step_failed"
  self.st.dlq_add(sid, step, err)
  self.st.set_status(sid, SagaStatus.COMPENSATED, "", 0); return SagaStatus.COMPENSATED

 def _status(self, sid: str) -> SagaStatus:
  r = self.st.get_saga(sid); return SagaStatus(r[2]) if r else SagaStatus.FAILED

 def recover(self, force: bool = False) -> List[str]:
  recovered = []
  for sid, st, step, lease in self.st.get_pending():
   if force or lease == 0 or lease < time.time():
    if self.st.claim(sid, lease=30, force=force):
     self._recover_one(sid); recovered.append(sid)
  return recovered

 def _recover_one(self, sid: str):
  saga = self.st.get_saga(sid)
  if not saga: return
  _, _, status, _, _, oid, amt, items_json, addr = saga
  items = json.loads(items_json) if items_json else []
  o = type('O', (), {'oid': oid, 'amt': amt, 'items': items, 'addr': addr})()
  ev = self.st.audit(sid); done = [(e[0], e[2]) for e in ev if e[1] == "fwd"]
  failed_step = ""
  try:
   for name, fn in self.STEPS:
    if any(d[0] == name for d in done): continue
    self.st.set_status(sid, SagaStatus.RUNNING, name, time.time() + 30)
    for a in range(1, self.ma + 1):
     if self.fp.should_fail(name, a):
      self.st.event(sid, name, "fail", "", a)
      if a == self.ma:
       self.st.dlq_add(sid, name, f"{name} failed after {a} attempts"); raise Exception(f"{name} failed")
      self.sf(0.01); continue
     try: res = fn(self, o, sid); done.append((name, res)); self.st.event(sid, name, "fwd", res, a); break
     except Exception as e:
      self.st.event(sid, name, "fail", str(e), a)
      if a == self.ma:
       self.st.dlq_add(sid, name, str(e)); raise
      self.sf(0.01)
     if self.fp.should_crash(name):
      self.st.set_status(sid, SagaStatus.RUNNING, name, 0); raise _Crash(f"crash after {name}")
   self.st.set_status(sid, SagaStatus.COMPLETED, "", 0)
  except _Crash:
   return
  except Exception as e:
   failed_step = next((n for n, _ in self.STEPS if not any(d[0] == n for d in done)), "")
   self._comp(sid, done, str(e), failed_step)

 def run_many(self, rids: List[str], workers: int = 4) -> Dict[str, SagaStatus]:
  results = {}
  with ThreadPoolExecutor(max_workers=workers) as ex:
   futures = {ex.submit(self.run, rid, f"order-{rid}", 100.0, ["i"], "a"): rid for rid in rids}
   for f in as_completed(futures): rid = futures[f]; results[rid] = f.result()
  return results

 def audit(self, sid: str) -> List[Tuple]: return self.st.audit(sid)
 def dlq(self) -> List[Tuple]: return self.st.dlq_list()