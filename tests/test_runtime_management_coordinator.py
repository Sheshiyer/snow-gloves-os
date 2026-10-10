import unittest,tempfile,pathlib,os,base64,hashlib,types,sys
from unittest.mock import patch
from lib.runtime_management_coordinator import RuntimeManagementCoordinator
from lib.runtime_operation_identity import checkpoint_digest,restore_digest
CRYPTO_CLI=str(pathlib.Path(os.environ.get("SG_TEST_CRYPTO_DIR",str(pathlib.Path(__file__).resolve().parents[1]/"infra/cloudflare-runtime")))/"backup_file_cli.mjs")
@unittest.skipUnless(sys.platform == "linux", "Linux coordinator proof required")
class Review(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.t.name).resolve();self.root.chmod(0o700);self.cli=self.root/'cli.mjs';self.cli.write_text('// owned fixture');self.cli.chmod(0o644)
  self.ctx={'instanceId':'heyzack','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'fixture-key'};self.sup=types.SimpleNamespace(_data_dir=str(self.root));self.key=base64.b64encode(os.urandom(32)).decode()
 def tearDown(self):self.t.cleanup()
 def make(self):return RuntimeManagementCoordinator(self.sup,self.ctx,self.key,'/usr/local/bin/node',str(self.cli))
 def test_constructor(self):self.make()
 def test_invalid_context_before_file_io(self):
  with patch('lib.runtime_management_coordinator.os.stat',side_effect=AssertionError('unexpected IO')) as probe:
   with self.assertRaises(RuntimeError):RuntimeManagementCoordinator(self.sup,{},self.key,'/usr/local/bin/node',str(self.cli))
   probe.assert_not_called()
 def test_invalid_identity_no_snapshot(self):
  c=self.make()
  with patch('lib.runtime_management_coordinator.write_bounded_snapshot') as snapshot:
   with self.assertRaises(RuntimeError):c.checkpoint({'job_id':'b'*32,'request_digest':'0'*64})
   snapshot.assert_not_called()
 def test_prepared_restore_reaches_decryption(self):
  c=self.make();sid='b'*32;rid='c'*32;dig=checkpoint_digest(self.ctx,sid);leaf='sg-encrypted-'+sid+'.bin';body=b'owned encrypted fixture';p=self.root/leaf;p.write_bytes(body);p.chmod(0o600);art={'leaf':leaf,'bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()};c._journal.prepare(sid,dig);c._journal.record_artifact(sid,dig,leaf,len(body),art['sha256']);payload={'restore_job_id':rid,'source_checkpoint_job_id':sid,'source_request_digest':dig,**art};payload['request_digest']=restore_digest(self.ctx,rid,sid,dig,art)
  with patch.object(c,'_run_cli',side_effect=RuntimeError('owned decrypt stop')) as decrypt:
   with self.assertRaises(RuntimeError):c.restore(payload)
   decrypt.assert_called_once()
 def crypto_fixture(self):
  import sqlite3
  from lib.runtime_supervisor import Supervisor
  db=self.root/'storage.sqlite';conn=sqlite3.connect(db);conn.execute('create table fixture(value text)');conn.execute("insert into fixture values('owned checkpoint')");conn.commit();conn.close();db.chmod(0o600)
  sup=Supervisor(str(self.root),['/usr/bin/true'],'s'*40,'m'*40)
  c=RuntimeManagementCoordinator(sup,self.ctx,self.key,'/usr/local/bin/node',CRYPTO_CLI)
  sid='b'*32;dig=checkpoint_digest(self.ctx,sid);record=c.checkpoint({'job_id':sid,'request_digest':dig});self.assertEqual(record['state'],'artifact-verified');self.assertEqual(c.checkpoint({'job_id':sid,'request_digest':dig}),record)
  payload={'restore_job_id':'c'*32,'source_checkpoint_job_id':sid,'source_request_digest':dig,**record['artifact']};payload['request_digest']=restore_digest(self.ctx,'c'*32,sid,dig,record['artifact']);return c,sup,payload
 def test_real_sqlite_crypto_journal_and_restore_bytes(self):
  c,sup,payload=self.crypto_fixture()
  with patch.object(sup,'restore') as mutation,patch.object(sup,'_check_http_health',return_value=True,create=True):
   result=c.restore(payload);self.assertEqual(result['state'],'completed-local');mutation.assert_called_once();self.assertTrue(mutation.call_args.args[0].startswith(b'SQLite format 3\x00'))
   with patch.object(c,'_run_cli') as crypto:
    replay=c.restore(payload);self.assertTrue(replay['historical']);crypto.assert_not_called();self.assertEqual(mutation.call_count,1)
 def test_failed_mutation_holds_retry_before_decryption(self):
  c,sup,payload=self.crypto_fixture()
  with patch.object(sup,'restore',side_effect=RuntimeError('owned restore fault')) as mutation:
   with self.assertRaises(RuntimeError):c.restore(payload)
   with patch.object(c,'_run_cli') as crypto:
    with self.assertRaises(RuntimeError):c.restore(payload)
    crypto.assert_not_called();self.assertEqual(mutation.call_count,1)
 def test_cli_rejects_nonhex_digest(self):
  c=self.make();response=types.SimpleNamespace(returncode=0,stdout=b'{"mode":"decrypt","output":"fixture.sqlite","bytes":32,"sha256":"'+b'z'*64+b'"}',stderr=b'')
  with patch('lib.runtime_management_coordinator.run_bounded',return_value=response.stdout):
   with self.assertRaises((RuntimeError,ValueError)):c._run_cli('decrypt','input.bin','fixture.sqlite')
 def test_constructor_rejects_binary_symlink_ancestor(self):
  alias=self.root/'alias';alias.symlink_to('/usr/local/bin',target_is_directory=True)
  with self.assertRaises(RuntimeError):RuntimeManagementCoordinator(self.sup,self.ctx,self.key,str(alias/'node'),str(self.cli))
 def test_late_health_true_stays_held(self):
  c,sup,payload=self.crypto_fixture()
  with patch.object(sup,'restore'),patch.object(sup,'_check_http_health',return_value=True,create=True),patch('lib.runtime_management_coordinator.time',types.SimpleNamespace(monotonic=iter([0,11]).__next__)):
   with self.assertRaises(RuntimeError):c.restore(payload)
  with self.assertRaises(RuntimeError):c._intents.reconcile(payload)
 def test_direct_concurrent_call_rejected(self):
  c=self.make();c._lock.acquire()
  try:
   with self.assertRaises(RuntimeError):c.checkpoint({'job_id':'b'*32,'request_digest':checkpoint_digest(self.ctx,'b'*32)})
  finally:c._lock.release()
 def test_cli_replacement_after_construction_held(self):
  c=self.make();self.cli.rename(self.root/'original-cli');self.cli.write_text('// foreign replacement');self.cli.chmod(0o644)
  response=types.SimpleNamespace(returncode=0,stdout=b'{"mode":"decrypt","output":"fixture.sqlite","bytes":32,"sha256":"'+b'a'*64+b'"}',stderr=b'')
  with patch('lib.runtime_management_coordinator.run_bounded',return_value=response.stdout) as launch:
   with self.assertRaises((RuntimeError,ValueError)):c._run_cli('decrypt','input.bin','fixture.sqlite')
   launch.assert_not_called()
 def test_same_inode_cli_change_held(self):
  c=self.make();self.cli.write_text('// changed same inode')
  with self.assertRaises(RuntimeError):c._verify_resources()
 def test_root_replacement_held_before_journal(self):
  c=self.make();moved=self.root.with_name(self.root.name+'-moved');self.root.rename(moved);self.root.mkdir(mode=0o700)
  try:
   with patch.object(c._journal,'prepare') as prepare:
    with self.assertRaises(RuntimeError):c.checkpoint({'job_id':'b'*32,'request_digest':checkpoint_digest(self.ctx,'b'*32)})
    prepare.assert_not_called()
  finally:
   import shutil
   shutil.rmtree(moved)
 def test_actual_sigkill_after_intent_holds_fresh_coordinator(self):
  import signal
  c,sup,payload=self.crypto_fixture()
  pid=os.fork()
  if pid==0:
   try:
    sup.restore=lambda raw:os.kill(os.getpid(),signal.SIGKILL)
    c.restore(payload)
   finally:os._exit(3)
  waited,status=os.waitpid(pid,0);self.assertEqual(waited,pid);self.assertTrue(os.WIFSIGNALED(status));self.assertEqual(os.WTERMSIG(status),signal.SIGKILL)
  fresh=RuntimeManagementCoordinator(sup,self.ctx,self.key,'/usr/local/bin/node',CRYPTO_CLI)
  with patch.object(fresh,'_run_cli') as decrypt,patch.object(sup,'restore') as mutation:
   with self.assertRaises(RuntimeError):fresh.restore(payload)
   decrypt.assert_not_called();mutation.assert_not_called()
  intent=self.root/('sg-restore-'+payload['restore_job_id']+'.json')
  import json
  record=json.loads(intent.read_text());self.assertEqual(record['state'],'mutation-intent');self.assertEqual(record['payload'],payload)
if __name__=='__main__':unittest.main(verbosity=2)
