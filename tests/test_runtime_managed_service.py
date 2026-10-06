import base64,dataclasses,importlib.util,pathlib,signal,sys,threading,time,unittest
from unittest.mock import patch
from lib import runtime_managed_service as m
def env():return {'SG_INSTANCE_ID':'heyzack','SG_IMAGE_DIGEST':'a'*64,'SG_BACKUP_KEY_ID':'fixture-key','SG_BACKUP_KEY':base64.b64encode(b'k'*32).decode(),'SG_MANAGEMENT_KEY':'m'*40,'SG_BACKEND_KEY':'b'*40,'STORAGE_ENCRYPTION_KEY':'s'*40,'DATA_DIR':'/owned','SG_NODE_EXECUTABLE':'/owned/node','SG_RUNTIME_SCRIPT':'/owned/server.js','SG_BACKUP_CLI':'/owned/backup.mjs'}
class Review(unittest.TestCase):
 def test_valid_config(self):
  with patch.object(m.sys,'platform','linux'):c=m.load_config(env())
  self.assertEqual(m._build_context(c)['keyId'],'fixture-key')
 def test_textually_shared_backup_management_key_denied(self):
  e=env();e['SG_MANAGEMENT_KEY']=e['SG_BACKUP_KEY']
  with patch.object(m.sys,'platform','linux'),self.assertRaises(ValueError):m.load_config(e)
 def test_nonboolean_fresh_denied_before_filesystem(self):
  with patch.object(m.sys,'platform','linux'):c=dataclasses.replace(m.load_config(env()),initialize_fresh=1)
  with patch.object(m.sys,'platform','linux'),patch.object(m,'_verify_data_dir') as fs,self.assertRaises(ValueError):m.run_service(c)
  fs.assert_not_called()
 def test_restore_downtime_does_not_kill_service(self):self.restore_case(False)
 def test_signal_during_restore_waits_for_management_owner(self):self.restore_case(True)
 def restore_case(self,signal_during):
  holders={};health_cycle=threading.Event();restoring=threading.Event();restored=threading.Event();server_stop=threading.Event();handlers={};log=[]
  class Supervisor:
   def __init__(self,**kw):self.child_pid=123;holders['sup']=self;self.health_count=0
   def start(self):pass
   def _check_http_health(self):
    self.health_count+=1
    if self.health_count>=2:health_cycle.set()
    return self.child_pid is not None
   def stop(self):log.append(('stop',restored.is_set()));self.child_pid=None
  class Coordinator:
   def __init__(self,**kw):pass
   def checkpoint(self,p):return {}
   def restore(self,p):
    holders['sup'].child_pid=None;restoring.set();time.sleep(0.75);holders['sup'].child_pid=124;restored.set();return {}
  class Server:
   def serve_forever(self):server_stop.wait(3)
   def shutdown(self):server_stop.set()
   def server_close(self):pass
  def factory(**kw):holders['restore']=kw['restore'];return Server()
  def controller():
   if not health_cycle.wait(2):return
   finish=handlers[signal.SIGTERM]
   if signal_during:
    caller=threading.Thread(target=lambda:holders['restore']({}));caller.start();restoring.wait(2);finish(signal.SIGTERM,None);caller.join(2)
   else:holders['restore']({});finish(signal.SIGTERM,None)
  worker=threading.Thread(target=controller);worker.start()
  with patch.object(m.sys,'platform','linux'),patch.object(m,'_verify_data_dir'),patch.object(m,'_snapshot_all_paths',return_value={}),patch.object(m,'_verify_snapshots'),patch.object(m,'InitializingSupervisor',Supervisor),patch.object(m,'RuntimeManagementCoordinator',Coordinator),patch.object(m,'create_managed_server',factory),patch.object(m.signal,'getsignal',return_value=signal.SIG_DFL),patch.object(m.signal,'signal',side_effect=lambda n,h:handlers.__setitem__(n,h)):
   try:m.run_service(m.load_config(env()))
   finally:worker.join(3)
  self.assertTrue(restoring.is_set());self.assertTrue(restored.is_set());self.assertEqual(log,[('stop',True)])
 def lifecycle_case(self,case):
  log=[];handlers={};done=threading.Event();counts={'health':0,'shutdown':0,'close':0,'stop':0,'factory':0}
  class Supervisor:
   child_pid=123
   def __init__(self,**kw):self.kw=kw;self.health_count=0
   def start(self):
    log.append('start')
    if case=='signal-start':handlers[signal.SIGTERM](signal.SIGTERM,None)
   def _check_http_health(self):
    counts['health']+=1
    if case=='unhealthy':return counts['health']==1
    if case=='normal' or case=='stop-failed':handlers[signal.SIGTERM](signal.SIGTERM,None)
    return True
   def stop(self):
    counts['stop']+=1
    if case=='stop-failed':raise RuntimeError('owned secret fixture')
  class Coordinator:
   def __init__(self,**kw):
    if case=='coordinator-failed':raise RuntimeError('owned fixture')
   def checkpoint(self,p):return {}
   def restore(self,p):return {}
  class Server:
   def serve_forever(self):
    if case=='server-died':return
    done.wait(3)
   def shutdown(self):counts['shutdown']+=1;done.set()
   def server_close(self):counts['close']+=1
  def factory(**kw):
   counts['factory']+=1;self.assertIs(kw['admission_probe'](),False)
   if case=='health-before-bind':
    self.assertGreaterEqual(counts['health'],1,'listener created before initial child health');handlers[signal.SIGTERM](signal.SIGTERM,None)
   return Server()
  patches=[patch.object(m.sys,'platform','linux'),patch.object(m,'_verify_data_dir'),patch.object(m,'_snapshot_all_paths',return_value={}),patch.object(m,'_verify_snapshots'),patch.object(m,'InitializingSupervisor',Supervisor),patch.object(m,'RuntimeManagementCoordinator',Coordinator),patch.object(m,'create_managed_server',factory),patch.object(m.signal,'getsignal',return_value=signal.SIG_DFL),patch.object(m.signal,'signal',side_effect=lambda n,h:handlers.__setitem__(n,h))]
  if case=='root-changed-before-start':patches[1]=patch.object(m,'_verify_data_dir',side_effect=[('owned',),('replaced',)])
  if case=='script-changed-before-start':patches[3]=patch.object(m,'_verify_snapshots',side_effect=RuntimeError('script changed'))
  if case=='late-health':patches.append(patch.object(m.time,'monotonic',side_effect=lambda values=iter([0.0,0.0,11.0]):next(values,11.0)))
  if case=='thread-start-failed':patches.append(patch.object(m.threading.Thread,'start',side_effect=RuntimeError('owned fixture')))
  import contextlib
  with contextlib.ExitStack() as stack:
   for p in patches:stack.enter_context(p)
   if case in ('normal','signal-start','health-before-bind'):m.run_service(m.load_config(env()))
   else:
    with self.assertRaises(RuntimeError):m.run_service(m.load_config(env()))
  self.assertEqual(counts['stop'],1)
  if case=='thread-start-failed':self.assertEqual(counts['shutdown'],0);self.assertEqual(counts['close'],1)
  if case in ('root-changed-before-start','script-changed-before-start'):self.assertEqual(log,[]);self.assertEqual(counts['factory'],0)
  if case=='signal-start':self.assertEqual(counts['factory'],0,'service bound after stop request')
 def test_changed_data_root_denies_before_start(self):self.lifecycle_case('root-changed-before-start')
 def test_changed_script_denies_before_start(self):self.lifecycle_case('script-changed-before-start')
 def test_late_startup_health_is_denied(self):self.lifecycle_case('late-health')
 def test_initial_health_precedes_listener_binding(self):self.lifecycle_case('health-before-bind')
 def test_partial_coordinator_failure_stops_child(self):self.lifecycle_case('coordinator-failed')
 def test_thread_start_failure_does_not_shutdown_unstarted_server(self):self.lifecycle_case('thread-start-failed')
 def test_unhealthy_monitor_fails(self):self.lifecycle_case('unhealthy')
 def test_unexpected_server_exit_fails(self):self.lifecycle_case('server-died')
 def test_normal_signal_stops_service(self):self.lifecycle_case('normal')
 def test_stop_error_propagates(self):self.lifecycle_case('stop-failed')
 def test_signal_during_start_does_not_bind_listener(self):self.lifecycle_case('signal-start')
 def test_main_redacts_failure_and_returns_nonzero(self):
  import contextlib,io
  stderr=io.StringIO()
  with patch.object(m,'load_config',side_effect=RuntimeError('owned secret fixture')),contextlib.redirect_stderr(stderr):self.assertEqual(m.main(),1)
  self.assertEqual(stderr.getvalue(),'Managed runtime unavailable\n')
 def test_data_root_special_mode_denied(self):
  import tempfile,os
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp).resolve();os.chmod(root,0o2700)
   with self.assertRaises(ValueError):m._verify_data_dir(str(root),True)
 def test_data_root_symlink_denied(self):
  import tempfile,os
  with tempfile.TemporaryDirectory() as tmp:
   base=pathlib.Path(tmp).resolve();root=base/'owned';root.mkdir(mode=0o700);link=base/'alias';link.symlink_to(root)
   with self.assertRaises(ValueError):m._verify_data_dir(str(link),True)
 def test_data_root_fresh_refuses_existing_file(self):
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp).resolve();(root/'foreign').write_text('owned fixture')
   with self.assertRaises(ValueError):m._verify_data_dir(str(root),True)
 def test_trusted_path_symlink_denied(self):
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
   base=pathlib.Path(tmp).resolve();f=base/'owned';f.write_text('fixture');link=base/'alias';link.symlink_to(f)
   with self.assertRaises(ValueError):m._stat_and_verify_trusted_path(str(link))
 def test_trusted_path_writable_by_group_denied(self):
  import tempfile,os
  with tempfile.TemporaryDirectory() as tmp:
   f=pathlib.Path(tmp).resolve()/'owned';f.write_text('fixture');os.chmod(f,0o660)
   with self.assertRaises(ValueError):m._stat_and_verify_trusted_path(str(f))
 def test_nonexecutable_node_denied_before_supervisor(self):self.permission_case(0o600,0o600)
 def test_executable_backup_cli_denied_before_supervisor(self):self.permission_case(0o700,0o700)
 def permission_case(self,node_mode,cli_mode):
  import tempfile,os
  with tempfile.TemporaryDirectory() as tmp:
   root=pathlib.Path(tmp).resolve();os.chmod(root,0o700);e=env();e['DATA_DIR']=str(root);(root/'storage.sqlite').write_bytes(b'fixture')
   for key,name in [('SG_NODE_EXECUTABLE','node'),('SG_RUNTIME_SCRIPT','server.js'),('SG_BACKUP_CLI','backup.mjs')]:
    p=root/name;p.write_text('fixture');os.chmod(p,node_mode if key=='SG_NODE_EXECUTABLE' else cli_mode if key=='SG_BACKUP_CLI' else 0o600);e[key]=str(p)
   with patch.object(m.sys,'platform','linux'),patch.object(m,'InitializingSupervisor',side_effect=AssertionError('supervisor created before executable validation')) as constructor,self.assertRaises(ValueError):m.run_service(m.load_config(e))
   constructor.assert_not_called()
if __name__=='__main__':unittest.main(verbosity=2)
