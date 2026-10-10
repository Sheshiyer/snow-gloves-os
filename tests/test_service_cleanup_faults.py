import base64,contextlib,signal,threading,time,unittest
from unittest.mock import patch
from lib import runtime_managed_service as m
from lib import runtime_management_http as gate_module
REAL_LOCK=threading.Lock
REAL_START=threading.Thread.start
ENV={'SG_INSTANCE_ID':'owned','SG_IMAGE_DIGEST':'a'*64,'SG_BACKUP_KEY_ID':'fixture-key','SG_BACKUP_KEY':base64.b64encode(b'k'*32).decode(),'SG_MANAGEMENT_KEY':'m'*40,'SG_BACKEND_KEY':'b'*40,'STORAGE_ENCRYPTION_KEY':'s'*40,'DATA_DIR':'/owned','SG_NODE_EXECUTABLE':'/owned/node','SG_RUNTIME_SCRIPT':'/owned/server.js','SG_BACKUP_CLI':'/owned/backup.mjs'}
class CleanupProof(unittest.TestCase):
 def exercise(self,case):
  handlers={};records=[];done=threading.Event();now=[0.0]
  class Supervisor:
   child_pid=123
   def __init__(self,**kw):self.count=0
   def start(self):pass
   def _check_http_health(self):
    self.count+=1
    if self.count>=2:handlers[signal.SIGTERM](signal.SIGTERM,None)
    return True
   def stop(self):
    if case=='late-stop':now[0]=70
  class Coordinator:
   def __init__(self,**kw):pass
   def checkpoint(self,p):return {}
   def restore(self,p):return {}
  class Server:
   def serve_forever(self):done.wait(3)
   def shutdown(self):done.set()
   def server_close(self):done.set()
  def capture(sig,handler):handlers[sig]=handler;records.append((sig,handler))
  class FaultLock:
   def __init__(self):self.inner=REAL_LOCK()
   def acquire(self,*args,**kw):
    if kw.get('timeout',0)>1:raise RuntimeError('owned acquire fault')
    return self.inner.acquire(*args,**kw)
   def locked(self):return self.inner.locked()
   def release(self):self.inner.release()
   def __enter__(self):self.inner.acquire();return self
   def __exit__(self,*args):self.inner.release()
  def start(thread):
   if getattr(getattr(thread,'_target',None),'__name__','')=='_do_shutdown':raise RuntimeError('owned start fault')
   return REAL_START(thread)
  patches=[patch.object(m.sys,'platform','linux'),patch.object(m,'_verify_data_dir',return_value=(1,2,0,0o40700)),patch.object(m,'_snapshot_all_paths',return_value={}),patch.object(m,'_verify_snapshots'),patch.object(m,'InitializingSupervisor',Supervisor),patch.object(m,'RuntimeManagementCoordinator',Coordinator),patch.object(m,'create_managed_server',side_effect=lambda **kw:Server()),patch.object(m.signal,'getsignal',return_value=signal.SIG_DFL),patch.object(m.signal,'signal',side_effect=capture),patch.object(m.time,'monotonic',side_effect=lambda:now[0])]
  if case=='acquire-fault':patches.append(patch.object(m.threading,'Lock',FaultLock))
  if case=='shutdown-start-fault':patches.append(patch.object(m.threading.Thread,'start',start))
  with contextlib.ExitStack() as stack:
   for p in patches:stack.enter_context(p)
   with self.assertRaises(RuntimeError):m.run_service(m.load_config(ENV))
  self.assertEqual(records[-2:],[(signal.SIGINT,signal.SIG_DFL),(signal.SIGTERM,signal.SIG_DFL)])
 def test_late_child_stop_held(self):self.exercise('late-stop')
 def test_lock_fault_restores_signals(self):self.exercise('acquire-fault')
 def test_shutdown_thread_start_fault_restores_signals(self):self.exercise('shutdown-start-fault')
 def test_timeout_subclass_rejected(self):
  class Number(int):pass
  with self.assertRaises(ValueError):gate_module.OperationGate().wait_idle(Number(1))
if __name__=='__main__':unittest.main(verbosity=2)
