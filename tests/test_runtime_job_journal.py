import unittest,tempfile,pathlib,hashlib,os,json,stat,subprocess,sys,fcntl
from unittest import mock
import lib.runtime_job_journal as module
from lib.runtime_job_journal import LocalJobJournal
@unittest.skipUnless(sys.platform == "linux", "Linux journal publication required")
class Review(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name).resolve();self.root.chmod(0o700);self.j=LocalJobJournal(str(self.root));self.job='a'*32;self.digest='b'*64;self.leaf='sg-encrypted-'+'c'*32+'.bin';self.body=b'owned encrypted fixture';self.sha=hashlib.sha256(self.body).hexdigest()
 def tearDown(self):self.temp.cleanup()
 def artifact(self):
  p=self.root/self.leaf;p.write_bytes(self.body);p.chmod(0o600);return p
 def prepare(self):return self.j.prepare(self.job,self.digest)
 def verify(self):return self.j.record_artifact(self.job,self.digest,self.leaf,len(self.body),self.sha)
 def test_prepare_and_resume(self):
  r=self.prepare();self.assertEqual(r['state'],'prepared');self.assertEqual(self.j.reconcile(self.job,self.digest),r);self.assertEqual(self.prepare(),r)
 def test_conflicting_digest_denied(self):
  self.prepare()
  with self.assertRaises(RuntimeError):self.j.prepare(self.job,'d'*64)
 def test_artifact_verified_and_rehashed(self):
  self.prepare();p=self.artifact();r=self.verify();self.assertEqual(r['state'],'artifact-verified');self.assertEqual(self.j.reconcile(self.job,self.digest),r);p.write_bytes(b'x'*len(self.body))
  with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
 def test_missing_journal_does_not_recreate(self):
  self.artifact()
  with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
  self.assertFalse((self.root/('sg-job-'+self.job+'.json')).exists())
 def test_missing_artifact_denied(self):
  self.prepare()
  with self.assertRaises(RuntimeError):self.verify()
 def test_wrong_hash_denied(self):
  self.prepare();self.artifact()
  with self.assertRaises(RuntimeError):self.j.record_artifact(self.job,self.digest,self.leaf,len(self.body),'0'*64)
 def test_journal_extra_field_denied(self):
  self.prepare();p=self.root/('sg-job-'+self.job+'.json');d=json.loads(p.read_text());d['remote_ack']=True;p.write_text(json.dumps(d));p.chmod(0o600)
  with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
 def test_duplicate_json_key_denied(self):
  self.prepare();p=self.root/('sg-job-'+self.job+'.json');s=p.read_text();p.write_text(s[:-1]+',"job_id":"'+self.job+'"}');p.chmod(0o600)
  with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
 def test_artifact_symlink_denied(self):
  self.prepare();other=self.root/'other';other.write_bytes(self.body);other.chmod(0o600);(self.root/self.leaf).symlink_to(other)
  with self.assertRaises(RuntimeError):self.verify()
 def test_artifact_hardlink_denied(self):
  self.prepare();p=self.artifact();os.link(p,self.root/'alias')
  with self.assertRaises(RuntimeError):self.verify()
 def test_return_mutation_does_not_change_journal(self):
  r=self.prepare();r['state']='remote-acknowledged';self.assertEqual(self.j.reconcile(self.job,self.digest)['state'],'prepared')
 def test_missing_prior_prepare_denied(self):
  self.artifact()
  with self.assertRaises(RuntimeError):self.verify()
 def test_trailing_newline_identity_denied(self):
  with self.assertRaises(RuntimeError):self.j.prepare(self.job+'\n',self.digest)
 def test_symlink_ancestor_denied(self):
  with tempfile.TemporaryDirectory() as parent:
   base=pathlib.Path(parent).resolve();(base/'alias').symlink_to(self.root);(self.root/'child').mkdir(mode=0o700)
   with self.assertRaises(RuntimeError):LocalJobJournal(str(base/'alias'/'child')).prepare(self.job,self.digest)
 def test_foreign_temp_replacement_denied(self):
  original=self.j._write_temp_journal
  def replace_temp(fd,content):
   name,ino=original(fd,content);os.unlink(name,dir_fd=fd);new=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=fd);os.write(new,b'foreign');os.close(new);return name,ino
  self.j._write_temp_journal=replace_temp
  with self.assertRaises(RuntimeError):self.prepare()
 def test_artifact_change_during_publication_denied(self):
  self.prepare();p=self.artifact();original=self.j._write_temp_journal
  def mutate(fd,content):
   result=original(fd,content);p.write_bytes(b'x'*len(self.body));return result
  self.j._write_temp_journal=mutate
  with self.assertRaises(RuntimeError):self.verify()
 def test_directory_fsync_failure_no_success_reconcile(self):
  original=os.fsync
  def fail(fd):
   if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('fixture')
   return original(fd)
  with mock.patch.object(module.os,'fsync',side_effect=fail):
   with self.assertRaises(RuntimeError):self.prepare()
  self.assertEqual(self.j.reconcile(self.job,self.digest)['state'],'prepared')
 def test_file_fsync_failure_no_journal(self):
  with mock.patch.object(module.os,'fsync',side_effect=OSError('fixture')):
   with self.assertRaises(RuntimeError):self.prepare()
  self.assertFalse((self.root/('sg-job-'+self.job+'.json')).exists())
  self.assertEqual(list(self.root.iterdir()),[])
 def test_root_movement_held(self):
  original=self.j._write_temp_journal;moved=self.root.with_name(self.root.name+'-moved')
  def move(fd,content):
   result=original(fd,content);self.root.rename(moved);self.root.mkdir(mode=0o700);return result
  self.j._write_temp_journal=move
  try:
   with self.assertRaises(RuntimeError):self.prepare()
  finally:
   self.root.rmdir();moved.rename(self.root)
 def test_artifact_path_replacement_during_read_held(self):
  self.prepare();p=self.artifact();self.verify();original=os.read;swapped=[False]
  def swap(fd,size):
   result=original(fd,size)
   if size==65536 and not swapped[0]:
    swapped[0]=True;p.rename(self.root/'old');p.write_bytes(b'x'*len(self.body));p.chmod(0o600)
   return result
  with mock.patch.object(module.os,'read',side_effect=swap):
   with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
 def test_crossprocess_lock_contention_held(self):
  code="import os,fcntl,sys;fd=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY);fcntl.flock(fd,fcntl.LOCK_EX);print('locked',flush=True);sys.stdin.read()"
  child=subprocess.Popen([sys.executable,'-c',code,str(self.root)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  try:
   self.assertEqual(child.stdout.readline().strip(),'locked')
   with self.assertRaises(RuntimeError):self.prepare()
  finally:child.communicate('stop',timeout=5)
 def kill_publication(self,after):
  code="import os,sys,signal;import lib.runtime_job_journal as module;from lib.runtime_job_journal import LocalJobJournal;original=module._publish_new\ndef interrupted(*a,**kw):\n if sys.argv[4]=='after':original(*a,**kw)\n os.kill(os.getpid(),signal.SIGKILL)\nmodule._publish_new=interrupted;LocalJobJournal(sys.argv[1]).prepare(sys.argv[2],sys.argv[3]);print('success')"
  result=subprocess.run([sys.executable,'-c',code,str(self.root),self.job,self.digest,'after' if after else 'before'],capture_output=True,text=True,timeout=5)
  self.assertEqual(result.returncode,-9);self.assertEqual(result.stdout,'')
 def test_sigkill_before_publication_held(self):
  self.kill_publication(False)
  with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
 def test_sigkill_after_publication_reconciles_same_local_job(self):
  self.kill_publication(True)
  self.assertEqual(self.j.reconcile(self.job,self.digest)['state'],'prepared')
  self.assertEqual((self.root/("sg-job-"+self.job+".json")).stat().st_nlink,1)
 def test_foreign_sameinode_temp_preserved(self):
  original=self.j._write_temp_journal;names=[]
  def mutate(fd,content):
   name,ino=original(fd,content);names.append(name);f=os.open(name,os.O_WRONLY|os.O_TRUNC,dir_fd=fd);os.write(f,b'foreign');os.close(f);return name,ino
  self.j._write_temp_journal=mutate
  with self.assertRaises(RuntimeError):self.prepare()
  self.assertEqual((self.root/names[0]).read_bytes(),b'foreign')
 def test_unknown_hardlink_is_held_and_preserved(self):
  self.prepare();p=self.root/('sg-job-'+self.job+'.json');os.link(p,self.root/'unknown-alias')
  with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
  self.assertTrue((self.root/'unknown-alias').exists())
 def test_new_publication_never_clobbers(self):
  old=self.root/'destination';old.write_bytes(b'old');src=self.root/'source';src.write_bytes(b'new');fd=os.open(self.root,os.O_DIRECTORY)
  try:
   with self.assertRaises(RuntimeError):module._publish_new(fd,'source','destination')
  finally:os.close(fd)
  self.assertEqual(old.read_bytes(),b'old');self.assertEqual(src.read_bytes(),b'new')
 def test_changed_sameinode_prior_record_denied(self):
  self.prepare();self.artifact();original=self.j._write_temp_journal
  def change(fd,content):
   result=original(fd,content);p=self.root/('sg-job-'+self.job+'.json');r=json.loads(p.read_text());r['request_digest']='e'*64;p.write_text(json.dumps(r,separators=(',',':')));return result
  self.j._write_temp_journal=change
  with self.assertRaises(RuntimeError):self.verify()
 def test_journal_fifo_denied_without_waiting(self):
  os.mkfifo(self.root/('sg-job-'+self.job+'.json'),0o600)
  with self.assertRaises(RuntimeError):self.j.reconcile(self.job,self.digest)
 def test_artifact_fifo_denied_without_waiting(self):
  self.prepare();os.mkfifo(self.root/self.leaf,0o600)
  with self.assertRaises(RuntimeError):self.verify()
if __name__=='__main__':unittest.main(verbosity=2)
