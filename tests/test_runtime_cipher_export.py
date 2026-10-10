import unittest,pathlib,tempfile,os,json,hashlib,threading,fcntl,sys,importlib,subprocess
from unittest.mock import patch
from lib import runtime_cipher_export as m
from lib.runtime_operation_identity import checkpoint_digest
@unittest.skipUnless(sys.platform=="linux", "Linux only")
class Proof(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.d=pathlib.Path(self.tmp.name);self.d.chmod(0o700);self.ctx={'instanceId':'owned','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'owned'};self.job='b'*32;self.payload={'job_id':self.job,'request_digest':checkpoint_digest(self.ctx,self.job)};self.f=self.d/('sg-encrypted-'+self.job+'.bin');self.j=self.d/('sg-job-'+self.job+'.json');self.fixture(b'x'*70000)
 def tearDown(self):self.tmp.cleanup()
 def fixture(self,data):
  self.data=data;self.f.write_bytes(data);self.f.chmod(0o600);self.rec={'schema':'sg.local-job.v1','job_id':self.job,'request_digest':self.payload['request_digest'],'state':'artifact-verified','artifact':{'leaf':self.f.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}};self.j.write_text(json.dumps(self.rec,separators=(',',':')));self.j.chmod(0o600);s=self.d.stat();self.ident=(s.st_dev,s.st_ino,s.st_uid,0o700)
 def reader(self,event=None):return m.CheckpointExportReader(str(self.d),self.ident,self.ctx,self.payload,event)
 def held(self,fn):
  with self.assertRaises(RuntimeError) as cm:fn()
  self.assertEqual(str(cm.exception),'Cipher export held');self.assertTrue(cm.exception.__suppress_context__)
 def test_sizes(self):
  for n in [1,65536,65537,64*1024*1024+4136]:
   self.fixture(b'x'*n)
   with self.reader() as r:
    ctx,rec=r.manifest();self.assertEqual(rec,self.rec);self.assertEqual(ctx,self.ctx);h=hashlib.sha256();total=0
    for c in r.iter_chunks():self.assertLessEqual(len(c),65536);h.update(c);total+=len(c)
    self.assertEqual(total,n);self.assertEqual(h.hexdigest(),self.rec['artifact']['sha256'])
 def test_corrupt_before_enter(self):self.f.write_bytes(b'y'*len(self.data));self.held(lambda:self.reader().__enter__())
 def test_midstream_write_final_withheld(self):
  with self.reader() as r:
   g=r.iter_chunks();self.assertEqual(len(next(g)),65536)
   with self.f.open('r+b') as f:f.seek(69999);f.write(b'y')
   self.held(lambda:next(g))
 def test_midstream_journal_change(self):
  with self.reader() as r:
   g=r.iter_chunks();next(g);self.j.write_bytes(b'{}');self.held(lambda:next(g))
 def test_cancel(self):
  e=threading.Event()
  with self.reader(e) as r:
   g=r.iter_chunks();next(g);e.set();self.held(lambda:next(g));self.assertTrue(e.is_set())
 def test_fd_close(self):
  before=len(os.listdir('/proc/self/fd'));r=self.reader();r.__enter__();g=r.iter_chunks();next(g);g.close();r.close();self.assertEqual(len(os.listdir('/proc/self/fd')),before)
 def test_lock(self):
  with self.reader():self.held(lambda:self.reader().__enter__())
 def test_expired_before_enter(self):
  with patch.object(m.time,'monotonic',return_value=0):r=self.reader()
  with patch.object(m.time,'monotonic',return_value=16):self.held(r.__enter__)
 def test_late_final_observation(self):
  with self.reader() as r:
   g=r.iter_chunks();next(g);original=m.os.path.realpath
   def late(p):v=original(p);r._deadline=0;return v
   with patch.object(m.os.path,'realpath',side_effect=late):self.held(lambda:next(g))
 def test_manifest_fault_redaction(self):
  with self.reader() as r:
   with patch.object(m.os.path,'realpath',side_effect=RuntimeError('private diagnostic')):self.held(r.manifest)
 def test_bad_inputs_before_io(self):
  bad=dict(self.payload,request_digest='f'*64)
  with patch.object(m.os,'lstat',side_effect=AssertionError('filesystem touched')):self.held(lambda:m.CheckpointExportReader(str(self.d),self.ident,self.ctx,bad))
 def test_prepared(self):
  self.rec['state']='prepared';self.rec['artifact']=None;self.j.write_text(json.dumps(self.rec,separators=(',',':')));self.held(lambda:self.reader().__enter__())
 def test_file_modes(self):
  for mode in [0o644,0o4600]:self.f.chmod(mode);self.held(lambda:self.reader().__enter__())
 def test_hardlink(self):os.link(self.f,self.d/'alias');self.held(lambda:self.reader().__enter__())
 def test_fifo(self):self.f.unlink();os.mkfifo(self.f,0o600);self.held(lambda:self.reader().__enter__())
 def test_root_special_bits(self):self.d.chmod(0o1700);self.held(lambda:self.reader().__enter__())
 def test_parse_replacement(self):
  parser=m._parse_and_validate_record
  def replace(raw):v=parser(raw);self.j.unlink();self.j.write_bytes(raw);self.j.chmod(0o600);return v
  with patch.object(m,'_parse_and_validate_record',side_effect=replace):self.held(lambda:self.reader().__enter__())
 def test_closed_and_single_use(self):
  r=self.reader();self.held(r.manifest);r=self.reader()
  with r:list(r.iter_chunks());self.held(lambda:next(r.iter_chunks()))
  self.held(r.__enter__)
 def test_independent_imports(self):
  for package,base in [('scripts.lib.runtime_cipher_export',str(pathlib.Path(m.__file__).parents[2])),('lib.runtime_cipher_export',str(pathlib.Path(m.__file__).parents[1]))]:
   code='import sys,importlib;sys.path.insert(0,'+repr(base)+');importlib.import_module('+repr(package)+')';out=subprocess.run([sys.executable,'-I','-B','-c',code],capture_output=True,text=True);self.assertEqual(out.returncode,0,out.stderr)
 def test_zero_effects(self):
  before={p.name:(p.read_bytes(),p.stat().st_mode,p.stat().st_ino) for p in self.d.iterdir()}
  with self.reader() as r:r.manifest();list(r.iter_chunks())
  after={p.name:(p.read_bytes(),p.stat().st_mode,p.stat().st_ino) for p in self.d.iterdir()};self.assertEqual(before,after)
 def test_root_wrong_identity(self):
  self.ident=(self.ident[0],self.ident[1]+1,self.ident[2],self.ident[3]);self.held(lambda:self.reader().__enter__())
 def test_root_alias(self):
  alias=self.d.parent/(self.d.name+'-alias');alias.symlink_to(self.d)
  try:self.held(lambda:m.CheckpointExportReader(str(alias),self.ident,self.ctx,self.payload))
  finally:alias.unlink()
 def test_cipher_symlink(self):
  target=self.d/'target';self.f.rename(target);self.f.symlink_to(target);self.held(lambda:self.reader().__enter__())
 def test_stream_named_replacement(self):
  with self.reader() as r:
   g=r.iter_chunks();next(g);self.f.unlink();self.f.write_bytes(self.data);self.f.chmod(0o600);self.held(lambda:next(g))
 def test_cancel_before_enter(self):
  e=threading.Event();e.set();self.held(lambda:self.reader(e))
 def test_input_copy(self):
  r=self.reader();self.ctx['keyId']='changed';self.payload['job_id']='c'*32
  with r:ctx,record=r.manifest();self.assertEqual(ctx['keyId'],'owned');self.assertEqual(record['job_id'],'b'*32);self.assertEqual(b''.join(r.iter_chunks()),self.data)
 def test_journal_mutation_last_stat(self):
  with self.reader() as r:
   g=r.iter_chunks();next(g);original=m.os.fstat;inode=self.j.stat().st_ino;calls=0
   def observe(fd):
    nonlocal calls
    st=original(fd)
    if st.st_ino==inode:
     calls+=1
     if calls==2:self.j.write_bytes(b'{}')
    return st
   with patch.object(m.os,'fstat',side_effect=observe):self.held(lambda:next(g))
if __name__=='__main__':unittest.main(verbosity=2)
