import unittest,threading,time,math
from unittest.mock import patch
from lib import runtime_management_http as m
class GateProof(unittest.TestCase):
 def test_idle(self):g=m.OperationGate();self.assertTrue(g.wait_idle(.05));g.close_admission();self.assertTrue(g.wait_idle(.05))
 def test_busy_timeout_preserves_token(self):g=m.OperationGate();t=g.begin_stream();self.assertFalse(g.wait_idle(.04));g.end_stream(t);self.assertTrue(g.wait_idle(.04))
 def test_closing_rejects_new_allows_end(self):
  g=m.OperationGate();t=g.begin_stream();g.close_admission();g.close_admission()
  with self.assertRaises(RuntimeError):g.begin_stream()
  with self.assertRaises(RuntimeError):g.begin_mutation()
  self.assertFalse(g.wait_idle(.04));g.end_stream(t);self.assertTrue(g.wait_idle(.04))
 def test_mutation_end_after_close(self):g=m.OperationGate();g.begin_mutation();g.close_admission();self.assertFalse(g.wait_idle(.04));g.end_mutation();self.assertTrue(g.wait_idle(.04))
 def test_all_waiters_wake(self):
  g=m.OperationGate();g.begin_mutation();results=[];threads=[threading.Thread(target=lambda:results.append(g.wait_idle(1))) for _ in range(4)]
  for t in threads:t.start()
  time.sleep(.05);g.end_mutation()
  for t in threads:t.join(.4);self.assertFalse(t.is_alive())
  self.assertEqual(results,[True]*4)
 def test_all_tokens_required(self):
  g=m.OperationGate();t1=g.begin_stream();t2=g.begin_stream();g.end_stream(t1);self.assertFalse(g.wait_idle(.03));g.end_stream(t2);self.assertTrue(g.wait_idle(.03))
 def test_wait_lock_acquire_bounded(self):
  g=m.OperationGate();g._lock.acquire();start=time.monotonic()
  try:self.assertFalse(g.wait_idle(.05));self.assertLess(time.monotonic()-start,.3)
  finally:g._lock.release()
 def test_close_lock_acquire_bounded(self):
  g=m.OperationGate();g._lock.acquire();start=time.monotonic()
  try:
   with self.assertRaises(RuntimeError):g.close_admission()
   self.assertLess(time.monotonic()-start,1.4)
  finally:g._lock.release()
  t=g.begin_stream();g.end_stream(t)
 def test_invalid_timeout(self):
  g=m.OperationGate()
  for v in [True,False,0,-1,61,float('inf'),float('nan'),'1',None]:
   with self.assertRaises(ValueError):g.wait_idle(v)
 def test_late_idle_observation(self):
  g=m.OperationGate();values=iter([0,0,2,2,2,2,2])
  with patch.object(m.time,'monotonic',side_effect=lambda:next(values,2)):self.assertFalse(g.wait_idle(1))
 def test_spurious_event_wakeup(self):
  g=m.OperationGate();g.begin_mutation()
  with patch.object(threading.Event,'wait',return_value=True):self.assertFalse(g.wait_idle(.03))
  g.end_mutation()
if __name__=='__main__':unittest.main(verbosity=2)
