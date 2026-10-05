import unittest,tempfile,pathlib,json,subprocess,sys,os
from lib.runtime_restore_intent import RestoreIntentStore
from lib.runtime_operation_identity import restore_digest
@unittest.skipUnless(sys.platform == "linux", "Linux restore-intent publication required")
class Review(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name).resolve();self.root.chmod(0o700);self.context={'instanceId':'heyzack','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'owned-fixture-key'};self.art={'leaf':'sg-encrypted-'+'c'*32+'.bin','bytes':32,'sha256':'d'*64};self.payload={'restore_job_id':'b'*32,'source_checkpoint_job_id':'c'*32,'source_request_digest':'e'*64,**self.art};self.payload['request_digest']=restore_digest(self.context,'b'*32,'c'*32,'e'*64,self.art);self.store=RestoreIntentStore(str(self.root),self.context)
 def tearDown(self):self.temp.cleanup()
 def test_prepare_and_resume(self):
  r=self.store.prepare(self.payload);self.assertEqual(r['state'],'prepared');self.assertEqual(self.store.reconcile(self.payload),r)
 def test_invalid_identity_before_effect(self):
  with self.assertRaises(RuntimeError):self.store.prepare({**self.payload,'request_digest':'0'*64})
  self.assertEqual(list(self.root.iterdir()),[])
 def test_missing_record_held(self):
  with self.assertRaises(RuntimeError):self.store.reconcile(self.payload)
 def test_mutation_intent_holds_after_restart(self):
  self.store.prepare(self.payload);token=self.store.begin_mutation(self.payload);new=RestoreIntentStore(str(self.root),self.context)
  with self.assertRaises(RuntimeError):new.reconcile(self.payload)
  with self.assertRaises(RuntimeError):new.complete(self.payload,token,health_verified=True)
 def test_completion_requires_true_and_original_token(self):
  self.store.prepare(self.payload);token=self.store.begin_mutation(self.payload)
  with self.assertRaises(RuntimeError):self.store.complete(self.payload,token,health_verified=1)
  with self.assertRaises(RuntimeError):self.store.complete(self.payload,object(),health_verified=True)
  self.assertEqual(self.store.complete(self.payload,token,health_verified=True)['state'],'completed-local')
 def test_double_mutation_and_completion_held(self):
  self.store.prepare(self.payload);token=self.store.begin_mutation(self.payload)
  with self.assertRaises(RuntimeError):self.store.begin_mutation(self.payload)
  self.store.complete(self.payload,token,health_verified=True)
  with self.assertRaises(RuntimeError):self.store.complete(self.payload,token,health_verified=True)
 def test_historical_completion_reconciles(self):
  self.store.prepare(self.payload);token=self.store.begin_mutation(self.payload);r=self.store.complete(self.payload,token,health_verified=True);self.assertEqual(RestoreIntentStore(str(self.root),self.context).reconcile(self.payload),r)
 def test_changed_payload_denied(self):
  self.store.prepare(self.payload)
  with self.assertRaises(RuntimeError):self.store.begin_mutation({**self.payload,'sha256':'f'*64})
 def test_symlink_root_held(self):
  alias=self.root/'alias';alias.symlink_to(self.root)
  with self.assertRaises(RuntimeError):RestoreIntentStore(str(alias),self.context).prepare(self.payload)
 def test_actual_kill_after_durable_intent_held(self):
  self.store.prepare(self.payload);code="import sys,json,os,signal;from lib.runtime_restore_intent import RestoreIntentStore;s=RestoreIntentStore(sys.argv[1],json.loads(sys.argv[2]));s.begin_mutation(json.loads(sys.argv[3]));os.kill(os.getpid(),signal.SIGKILL)";r=subprocess.run([sys.executable,'-c',code,str(self.root),json.dumps(self.context),json.dumps(self.payload)],capture_output=True,text=True,timeout=5);self.assertEqual(r.returncode,-9)
  with self.assertRaises(RuntimeError):self.store.reconcile(self.payload)
 def test_directory_fsync_failure_must_hold(self):
  from unittest.mock import patch
  import stat
  real=os.fsync
  def fault(fd):
   if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('owned synthetic directory fsync failure')
   return real(fd)
  with patch('lib.runtime_restore_intent.os.fsync',side_effect=fault):
   with self.assertRaises(RuntimeError):self.store.prepare(self.payload)
 def test_root_move_before_publication_must_hold(self):
  from unittest.mock import patch
  import lib.runtime_restore_intent as module
  real=module._publish_new
  moved=self.root.with_name(self.root.name+'-moved')
  def swap(fd,temp,name):
   self.root.rename(moved);self.root.mkdir(mode=0o700)
   return real(fd,temp,name)
  try:
   with patch('lib.runtime_restore_intent._publish_new',side_effect=swap):
    with self.assertRaises(RuntimeError):self.store.prepare(self.payload)
  finally:
   import shutil
   shutil.rmtree(moved,ignore_errors=True)
 def test_foreign_scratch_inode_must_not_publish(self):
  from unittest.mock import patch
  real=self.store._write_temp_file
  foreign=None
  def swap(fd,raw,dev):
   nonlocal foreign
   name,ino=real(fd,raw,dev)
   (self.root/name).rename(self.root/'original-owned-scratch')
   foreign=self.root/name;foreign.write_bytes(raw);foreign.chmod(0o600)
   return name,ino
  with patch.object(self.store,'_write_temp_file',side_effect=swap):
   with self.assertRaises(RuntimeError):self.store.prepare(self.payload)
  self.assertTrue(foreign.exists())
  self.assertFalse((self.root/('sg-restore-'+'b'*32+'.json')).exists())
 def test_fsync_failure_preserves_foreign_scratch(self):
  from unittest.mock import patch
  import stat
  real=os.fsync
  foreign=[]
  def fault(fd):
   if stat.S_ISREG(os.fstat(fd).st_mode):
    scratch=next(self.root.glob('.tmp-restore-*'))
    scratch.rename(self.root/'original-owned-scratch')
    scratch.write_bytes(b'foreign fixture');scratch.chmod(0o600);foreign.append(scratch)
    raise OSError('synthetic file fsync failure')
   return real(fd)
  with patch('lib.runtime_restore_intent.os.fsync',side_effect=fault):
   with self.assertRaises((RuntimeError,OSError)):self.store.prepare(self.payload)
  self.assertEqual(foreign[0].read_bytes(),b'foreign fixture')
 def test_record_name_replacement_during_read_held(self):
  from unittest.mock import patch
  self.store.prepare(self.payload)
  name=self.root/('sg-restore-'+'b'*32+'.json')
  real=self.store._parse_and_validate_raw
  def swap(raw,payload):
   name.rename(self.root/'original-record')
   name.write_bytes(raw);name.chmod(0o600)
   return real(raw,payload)
  with patch.object(self.store,'_parse_and_validate_raw',side_effect=swap):
   with self.assertRaises(RuntimeError):self.store.reconcile(self.payload)
 def test_same_instance_lock_rejects_without_wait(self):
  import threading,time
  done=threading.Event();result=[]
  self.store._lock.acquire()
  def run():
   try:self.store.prepare(self.payload);result.append('accepted')
   except RuntimeError:result.append('held')
   finally:done.set()
  thread=threading.Thread(target=run);thread.start()
  rejected=done.wait(0.2)
  self.store._lock.release();thread.join(2)
  self.assertTrue(rejected);self.assertEqual(result,['held'])
 def test_actual_sigkill_transition_matrix(self):
  child = """import sys,json,os,signal
import lib.runtime_restore_intent as module
root,ctx,payload,stage,position=sys.argv[1:]
s=module.RestoreIntentStore(root,json.loads(ctx));p=json.loads(payload)
if stage!='prepare':s.prepare(p)
if stage=='complete':token=s.begin_mutation(p)
original=module._publish_new if stage=='prepare' else module.os.rename
def killed(*args,**kwargs):
 if position=='before':os.kill(os.getpid(),signal.SIGKILL)
 result=original(*args,**kwargs)
 os.kill(os.getpid(),signal.SIGKILL)
 return result
if stage=='prepare':module._publish_new=killed
else:module.os.rename=killed
if stage=='prepare':s.prepare(p)
elif stage=='begin':s.begin_mutation(p)
else:s.complete(p,token,health_verified=True)
"""
  expected={('prepare','before'):None,('prepare','after'):'prepared',('begin','before'):'prepared',('begin','after'):None,('complete','before'):None,('complete','after'):'completed-local'}
  for (stage,position),state in expected.items():
   with self.subTest(stage=stage,position=position):
    root=self.root/(stage+'-'+position);root.mkdir(mode=0o700)
    result=subprocess.run([sys.executable,'-c',child,str(root),json.dumps(self.context),json.dumps(self.payload),stage,position],capture_output=True,text=True,timeout=5)
    self.assertEqual(result.returncode,-9,result.stderr)
    store=RestoreIntentStore(str(root),self.context)
    if state is None:
     with self.assertRaises(RuntimeError):store.reconcile(self.payload)
    else:self.assertEqual(store.reconcile(self.payload)['state'],state)
 def test_cleanup_preserves_hardlinked_scratch(self):
  path=self.root/'scratch';path.write_bytes(b'owned');path.chmod(0o600)
  os.link(path,self.root/'alias');fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
  try:self.store._cleanup_temp(fd,'scratch',path.stat().st_ino,b'owned')
  finally:os.close(fd)
  self.assertTrue(path.exists())
 def test_cleanup_preserves_path_replacement_during_read(self):
  from unittest.mock import patch
  path=self.root/'scratch';path.write_bytes(b'owned');path.chmod(0o600)
  ino=path.stat().st_ino;real=os.read;fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY)
  def swap(handle,count):
   raw=real(handle,count);path.rename(self.root/'original-scratch');path.write_bytes(b'foreign');path.chmod(0o600);return raw
  try:
   with patch('lib.runtime_restore_intent.os.read',side_effect=swap):self.store._cleanup_temp(fd,'scratch',ino,b'owned')
  finally:os.close(fd)
  self.assertEqual(path.read_bytes(),b'foreign')
 def test_cross_process_directory_lock_held(self):
  import fcntl
  fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  code="import sys,json;from lib.runtime_restore_intent import RestoreIntentStore;s=RestoreIntentStore(sys.argv[1],json.loads(sys.argv[2]));s.prepare(json.loads(sys.argv[3]))"
  try:result=subprocess.run([sys.executable,'-c',code,str(self.root),json.dumps(self.context),json.dumps(self.payload)],capture_output=True,text=True,timeout=2)
  finally:os.close(fd)
  self.assertNotEqual(result.returncode,0);self.assertIn('Restore intent held',result.stderr);self.assertEqual(list(self.root.iterdir()),[])
 def test_malformed_record_bounds_and_aliases_held(self):
  name=self.root/('sg-restore-'+'b'*32+'.json')
  for raw in [b'{}',b'x'*2049,b'{"state":"prepared","state":"prepared"}',b'{"state":NaN}',b'\xff']:
   with self.subTest(raw=raw[:30]):
    name.write_bytes(raw);name.chmod(0o600)
    with self.assertRaises(RuntimeError):self.store.reconcile(self.payload)
  name.unlink();name.symlink_to(self.root/'missing')
  with self.assertRaises(RuntimeError):self.store.reconcile(self.payload)
if __name__=='__main__':unittest.main(verbosity=2)
