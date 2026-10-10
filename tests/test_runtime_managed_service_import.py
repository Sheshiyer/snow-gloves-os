import base64,contextlib,inspect,signal,threading,time,unittest
from unittest.mock import patch
from lib import runtime_managed_service as m
from lib.runtime_import_request_registry import ImportRequestRegistry
class ServiceImport(unittest.TestCase):
 def run_owned(self, action=None, close_fault=None, count=None, body_fault=None, drain=False):
  log=[];self.last_log=log;handlers={};done=threading.Event();registry=ImportRequestRegistry();box={};serve_errors=[]
  class Sup:
   child_pid=123
   def __init__(self,**kw):pass
   def start(self):
    if body_fault is not None:raise body_fault
   def _check_http_health(self):return True
   def stop(self):log.append('stop')
  class Coordinator:
   def __init__(self,**kw):pass
   def checkpoint(self,p):return {}
   def restore(self,p):return {}
  class Server:
   def serve_forever(self):
    box['thread']=threading.current_thread()
    if not done.wait(2):serve_errors.append('owned serve timeout')
   def shutdown(self):
    log.append('shutdown')
    if drain:registry.unregister(box['handle'])
    done.set()
   def server_close(self):log.append('close')
  def factory(**kw):
   box['kw']=kw
   self.assertIs(kw['import_request_registry'],registry)
   old=kw['gate'].close_admission
   def gate_close():
    self.assertTrue(registry.is_closed());log.append('gate-close')
    if 'event' in box:self.assertTrue(box['event'].is_set())
    return old()
   kw['gate'].close_admission=gate_close
   if action:action(kw,registry,box)
   self.assertFalse(registry.is_closed())
   handlers[signal.SIGTERM](signal.SIGTERM,None)
   self.assertFalse(registry.is_closed(),'SIG handler took registry ownership')
   return Server()
  env={'SG_INSTANCE_ID':'heyzack','SG_IMAGE_DIGEST':'a'*64,'SG_BACKUP_KEY_ID':'fixture-key','SG_BACKUP_KEY':base64.b64encode(b'k'*32).decode(),'SG_MANAGEMENT_KEY':'m'*40,'SG_BACKEND_KEY':'b'*40,'STORAGE_ENCRYPTION_KEY':'s'*40,'DATA_DIR':'/owned','SG_NODE_EXECUTABLE':'/owned/node','SG_RUNTIME_SCRIPT':'/owned/server.js','SG_BACKUP_CLI':'/owned/backup.mjs'}
  with contextlib.ExitStack() as stack:
   for p in [patch.object(m.sys,'platform','linux'),patch.object(m,'_verify_data_dir',return_value=(1,2,3,0o40700)),patch.object(m,'_snapshot_all_paths',return_value={}),patch.object(m,'_verify_snapshots'),patch.object(m,'InitializingSupervisor',Sup),patch.object(m,'RuntimeManagementCoordinator',Coordinator),patch.object(m,'ImportRequestRegistry',return_value=registry),patch.object(m,'create_managed_server',factory),patch.object(m.signal,'getsignal',return_value=signal.SIG_DFL),patch.object(m.signal,'signal',side_effect=lambda n,h:handlers.__setitem__(n,h))]:stack.enter_context(p)
   if close_fault is not None:stack.enter_context(patch.object(registry,'close_and_cancel',side_effect=close_fault))
   if count is not None:stack.enter_context(patch.object(registry,'active_count',return_value=count))
   try:m.run_service(m.load_config(env))
   finally:
    if 'thread' in box:self.assertFalse(box['thread'].is_alive())
    self.assertEqual(serve_errors,[])
  return log,box
 def test_exact_trusted_forwarding(self):
  def action(kw,r,b):
   ev=threading.Event();deadline=int(time.monotonic())+10
   with patch.object(m,'import_remote_cipher_and_bind_journal',return_value={'fixture':True}) as wrapper:
    self.assertEqual(kw['import_cb']({}, {}, {}, 8,ev,deadline),{'fixture':True})
    self.assertEqual(wrapper.call_args.args[:2],('/owned',(1,2,3,0o700)))
    self.assertIs(wrapper.call_args.args[6],ev);self.assertIs(wrapper.call_args.kwargs['deadline'],deadline)
  log,box=self.run_owned(action);self.assertIn('stop',log)
 def test_invalid_deadlines_deny_wrapper(self):
  def action(kw,r,b):
   with patch.object(m,'import_remote_cipher_and_bind_journal') as wrapper:
    for value in [None,True,float('nan'),float('inf'),time.monotonic()-1,time.monotonic()+16]:
     with self.assertRaisesRegex(RuntimeError,'Managed import held'):kw['import_cb']({}, {}, {},8,threading.Event(),value)
    wrapper.assert_not_called()
  self.run_owned(action)
 def test_lock_wait_uses_original_deadline(self):
  def action(kw,r,b):
   lock=inspect.getclosurevars(kw['import_cb']).nonlocals['mgmt_lock'];self.assertTrue(lock.acquire(False));started=time.monotonic()
   try:
    with patch.object(m,'import_remote_cipher_and_bind_journal') as wrapper,self.assertRaises(RuntimeError):kw['import_cb']({}, {}, {},8,threading.Event(),started+.08)
    wrapper.assert_not_called();self.assertLess(time.monotonic()-started,1)
   finally:lock.release()
  self.run_owned(action)
 def test_verified_drain_unregister_allows_stop(self):
  def action(kw,r,b):b['handle'],b['event']=r.register()
  log,box=self.run_owned(action,drain=True);self.assertTrue(box['event'].is_set());self.assertLess(log.index('gate-close'),log.index('stop'))
 def test_retained_registry_denies_stop(self):
  def action(kw,r,b):b['handle'],b['event']=r.register()
  with self.assertRaisesRegex(RuntimeError,'Cleanup failed'):self.run_owned(action)
  self.assertNotIn('stop',self.last_log)
 def test_cleanup_controlflow_is_preserved(self):
  for exc in [KeyboardInterrupt('owned'),SystemExit(7)]:
   with self.subTest(kind=type(exc).__name__),self.assertRaises(type(exc)) as caught:self.run_owned(close_fault=exc)
   self.assertIs(caught.exception,exc);self.assertNotIn('stop',self.last_log)
 def test_primary_interrupt_beats_cleanup(self):
  first=KeyboardInterrupt('first')
  with self.assertRaises(KeyboardInterrupt) as caught:self.run_owned(close_fault=SystemExit(9),body_fault=first)
  self.assertIs(caught.exception,first);self.assertNotIn('stop',self.last_log)
 def test_wrong_registry_count_held(self):
  for value in [False,0.0]:
   with self.subTest(value=value),self.assertRaisesRegex(RuntimeError,'Cleanup failed'):self.run_owned(count=value)
   self.assertNotIn('stop',self.last_log)

 def test_main_uncertain_interrupt_returns_failure_redacted(self):
  import io
  output=io.StringIO()
  with patch.object(m,'load_config',return_value=object()),patch.object(m,'run_service',side_effect=KeyboardInterrupt('owned uncertain cleanup')),contextlib.redirect_stderr(output):
   self.assertEqual(m.main(),1)
  self.assertEqual(output.getvalue(),'Managed runtime unavailable\n')
