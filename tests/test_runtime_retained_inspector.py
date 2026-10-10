import unittest,tempfile,pathlib,os,hashlib,json,sys,types,traceback
from unittest.mock import patch
import lib.runtime_retained_inspector as m
from lib.runtime_job_journal import LocalJobJournal
from lib.runtime_operation_identity import checkpoint_digest,restore_digest
from lib.runtime_restore_intent import RestoreIntentStore
@unittest.skipUnless(sys.platform=="linux","Linux only")
class Review(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.t.name).resolve();self.root.chmod(0o700);st=self.root.stat();self.identity=(st.st_dev,st.st_ino,st.st_uid,0o700);self.ctx={"instanceId":"owned-inspector","runtimeVersion":"3.8.50","imageDigest":"c"*64,"keyId":"owned-key"};self.job="a"*32;self.digest=checkpoint_digest(self.ctx,self.job)
 def tearDown(self):self.t.cleanup()
 def inspect(self):return m.inspect_retained(str(self.root),self.identity,self.ctx)
 def journal(self,body=None):
  j=LocalJobJournal(str(self.root));j.prepare(self.job,self.digest)
  if body is not None:
   leaf="sg-encrypted-"+self.job+".bin";p=self.root/leaf;p.write_bytes(body);p.chmod(0o600);j.record_artifact(self.job,self.digest,leaf,len(body),hashlib.sha256(body).hexdigest())
  return j
 def snapshot(self):return {str(p.relative_to(self.root)):(p.lstat().st_mode,p.lstat().st_ino,p.lstat().st_size,hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in self.root.rglob("*")}
 def test_empty_and_zero_effects(self):
  before=self.snapshot();r=self.inspect();self.assertTrue(r["complete"]);self.assertEqual(r["external_writes_uncertain"],1);self.assertEqual(r["entries"],0);self.assertEqual(before,self.snapshot())
 def test_valid_encrypted_reference(self):
  self.journal(b"owned encrypted fixture");before=self.snapshot();r=self.inspect();self.assertEqual(r["artifact_journals"],1);self.assertEqual(r["verified_encrypted"],1);self.assertEqual(r["hashed_bytes"],23);self.assertEqual(before,self.snapshot())
 def test_interrupted_intent_and_unbound_evidence(self):
  self.journal(b"owned");rid="b"*32;art={"leaf":"sg-encrypted-"+self.job+".bin","bytes":5,"sha256":hashlib.sha256(b"owned").hexdigest()};p={"restore_job_id":rid,"source_checkpoint_job_id":self.job,"source_request_digest":self.digest,**art};p["request_digest"]=restore_digest(self.ctx,rid,self.job,self.digest,art);store=RestoreIntentStore(str(self.root),self.ctx);store.prepare(p);store.begin_mutation(p)
  for n in ["sg-snapshot-"+"c"*32+".sqlite","sg-restore-plain-"+rid+"-"+"d"*16+".sqlite",".sg-recovery-owned.sqlite"]:
   f=self.root/n;f.write_bytes(b"retained");f.chmod(0o600)
  r=self.inspect();self.assertEqual(r["mutation_intents"],1);self.assertEqual(r["unbound_snapshots"],1);self.assertEqual(r["unbound_plain_restores"],1);self.assertEqual(r["unbound_recovery"],1)
 def test_special_namespace_denied(self):
  f=self.root/"link";f.symlink_to("/tmp")
  with self.assertRaises(RuntimeError):self.inspect()
 def test_root_lock_contention(self):
  import fcntl
  fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:
   with self.assertRaises(RuntimeError):self.inspect()
  finally:os.close(fd)
 def test_record_replace_during_parse_denied(self):
  self.journal();target=self.root/("sg-job-"+self.job+".json");original=m._parse_and_validate_record
  def replace(raw):
   result=original(raw);p=self.root/"replacement";p.write_bytes(raw);p.chmod(0o600);os.replace(p,target);return result
  with patch.object(m,"_parse_and_validate_record",side_effect=replace):
   with self.assertRaises(RuntimeError):self.inspect()
 def test_nested_growth_during_parse_denied(self):
  self.journal();folder=self.root/"cache";folder.mkdir(mode=0o700);target=folder/"data";target.write_bytes(b"a");target.chmod(0o600);original=m._parse_and_validate_record
  def grow(raw):
   result=original(raw);target.write_bytes(b"changed nested content");return result
  with patch.object(m,"_parse_and_validate_record",side_effect=grow):
   with self.assertRaises(RuntimeError):self.inspect()
 def test_ordinary_fault_redacted(self):
  with patch.object(m.os,"scandir",side_effect=OSError("synthetic private diagnostic")):
   try:self.inspect()
   except RuntimeError as e:
    self.assertEqual(str(e),"Retained inspection held");self.assertNotIn("synthetic private diagnostic", "".join(traceback.format_exception(e)))
   else:self.fail("missing held")
 def test_validation_time_in_total_budget(self):
  original=m._validate_root_path;now=[0.0]
  def late(root,*args):result=original(root,*args);now[0]=3.0;return result
  with patch.object(m,"_validate_root_path",side_effect=late),patch.object(m.time,"monotonic",side_effect=lambda:now[0]):
   r=self.inspect();self.assertFalse(r["complete"])
 def test_final_root_observation_after_deadline_not_complete(self):
  original=m.os.path.realpath;now=[0.0];seen=[0]
  def late(path,*a,**kw):
   result=original(path,*a,**kw)
   if path==str(self.root):
    seen[0]+=1
    if seen[0]>=2:now[0]=3.0
   return result
  with patch.object(m.os.path,"realpath",side_effect=late),patch.object(m.time,"monotonic",side_effect=lambda:now[0]):
   r=self.inspect();self.assertFalse(r["complete"])
 def test_context_mismatch_held(self):
  self.journal();self.ctx["instanceId"]="other-owned-instance"
  with self.assertRaises(RuntimeError):self.inspect()
 def test_sparse_root_logical_limit_held(self):
  p=self.root/"large";fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.ftruncate(fd,536870913);os.close(fd)
  with self.assertRaises(RuntimeError):self.inspect()
 def test_hardlink_and_fifo_hold_without_read(self):
  p=self.root/"first";p.write_bytes(b"a");p.chmod(0o600);os.link(p,self.root/"second")
  with self.assertRaises(RuntimeError):self.inspect()
  (self.root/"second").unlink();p.unlink();os.mkfifo(self.root/"fifo",0o600)
  with self.assertRaises(RuntimeError):self.inspect()
 def test_bad_json_is_not_absent_record(self):
  p=self.root/("sg-job-"+self.job+".json");p.write_bytes(b'{"schema":0,"schema":1}');p.chmod(0o600)
  with self.assertRaises(RuntimeError):self.inspect()
 def test_nested_regular_counts_other_not_directory(self):
  folder=self.root/"cache";folder.mkdir(mode=0o755);p=folder/"x";p.write_bytes(b"owned");p.chmod(0o644)
  r=self.inspect();self.assertEqual(r["entries"],2);self.assertEqual(r["other_files"],1)
 def test_max_ciphertext_supported_not_false_budget_hold(self):
  length=64*1024*1024+4136;self.journal(b"z"*length);r=self.inspect();self.assertTrue(r["complete"]);self.assertEqual(r["hashed_bytes"],length);self.assertEqual(r["verified_encrypted"],1)
 def test_hash_budget_exhaustion_incomplete_no_verified(self):
  self.journal(b"owned");second="b"*32;j=LocalJobJournal(str(self.root));dig=checkpoint_digest(self.ctx,second);j.prepare(second,dig);leaf="sg-encrypted-"+second+".bin";p=self.root/leaf;p.write_bytes(b"another");p.chmod(0o600);j.record_artifact(second,dig,leaf,7,hashlib.sha256(b"another").hexdigest())
  with patch.object(m,"_MAX_HASH_TOTAL_BYTES",5):
   r=self.inspect();self.assertFalse(r["complete"]);self.assertEqual(r["verified_encrypted"],0)
 def test_synthetic_same_message_fault_context_still_redacted(self):
  def fault(*args):
   try:raise OSError("synthetic diagnostic detail")
   except OSError:raise RuntimeError("Retained inspection held")
  with patch.object(m.os,"scandir",side_effect=fault):
   try:self.inspect()
   except RuntimeError as e:self.assertNotIn("synthetic diagnostic detail","".join(traceback.format_exception(e)))
   else:self.fail("missing held")
 def test_missing_encrypted_reference_is_held(self):
  self.journal(b"owned");(self.root/("sg-encrypted-"+self.job+".bin")).unlink()
  with self.assertRaises(RuntimeError):self.inspect()
 def test_parser_same_message_exception_chain_redacted(self):
  self.journal()
  def fault(*args):
   try:raise OSError("synthetic parser detail")
   except OSError:raise RuntimeError("Retained inspection held")
  with patch.object(m,"_parse_and_validate_record",side_effect=fault):
   try:self.inspect()
   except RuntimeError as e:self.assertNotIn("synthetic parser detail","".join(traceback.format_exception(e)))
   else:self.fail("missing held")
if __name__=="__main__":unittest.main()
