import os,sys,stat,tempfile,shutil,unittest
from unittest.mock import patch
import scripts.lib.runtime_storage_guard as g
@unittest.skipUnless(sys.platform == "linux", "Requires Linux")
class Review(unittest.TestCase):
 def setUp(self):
  self.root=tempfile.mkdtemp();os.chmod(self.root,0o700);s=os.stat(self.root);self.identity=(s.st_dev,s.st_ino,s.st_uid,0o700);self.b=g.StorageBudget(min_free_bytes=1)
 def tearDown(self):
  if os.path.islink(self.root):os.unlink(self.root)
  shutil.rmtree(self.root,ignore_errors=True);shutil.rmtree(self.root+'-retained',ignore_errors=True)
 def pre(self,b=None):return g.preflight(self.root,self.identity,'checkpoint',b or self.b)
 def test_actual_artifact_names_charge_class_limits(self):
  for n in ['sg-snapshot-'+'a'*32+'.sqlite','sg-encrypted-'+'b'*32+'.bin','sg-job-'+'c'*32+'.json']:
   p=self.root+'/'+n;open(p,'wb').close();os.chmod(p,0o600)
  with self.assertRaises(RuntimeError):self.pre(g.StorageBudget(max_snapshots=1,min_free_bytes=1))
 def test_preflight_never_calls_unbounded_listdir(self):
  with patch.object(g.os,'listdir',side_effect=AssertionError('unbounded directory materialization')):self.pre()
 def test_platform_is_linux_only(self):
  with patch('sys.platform','darwin'):
   with self.assertRaises(RuntimeError):self.pre()
 def test_expected_owner_must_be_current_euid(self):
  with patch.object(g.os,'geteuid',return_value=self.identity[2]+1):
   with self.assertRaises(RuntimeError):self.pre()
 def test_final_symlink_replacement_to_same_original_inode_denied(self):
  original=os.stat;swapped=False
  def inspect(path,*a,**kw):
   nonlocal swapped
   if path==self.root and not swapped:
    swapped=True;os.rename(self.root,self.root+'-retained');os.symlink(self.root+'-retained',self.root)
   return original(path,*a,**kw)
  with patch.object(g.os,'stat',side_effect=inspect):
   with self.assertRaises(RuntimeError):self.pre()
 def test_file_growth_before_descriptor_close_denied(self):
  path=self.root+'/owned';open(path,'wb').close();os.chmod(path,0o600);close=os.close;grew=False
  def closing(fd):
   nonlocal grew
   try:name=os.readlink('/proc/self/fd/'+str(fd))
   except OSError:name=''
   if name==path and not grew:
    grew=True
    with open(path,'ab') as f:f.write(b'x'*65536)
   return close(fd)
  with patch.object(g.os,'close',side_effect=closing):
   with self.assertRaises(RuntimeError):self.pre()
 def test_deadline_after_final_named_observation_denied(self):
  original=os.stat;clock=[0.0]
  def inspect(path,*a,**kw):
   v=original(path,*a,**kw)
   if path==self.root:clock[0]=1.0
   return v
  with patch.object(g.os,'stat',side_effect=inspect),patch.object(g.time,'monotonic',side_effect=lambda:clock[0]):
   with self.assertRaises(RuntimeError):self.pre()

 def test_new_root_entry_during_final_observation_denied(self):
  original=os.stat;changed=False
  def inspect(path,*a,**kw):
   nonlocal changed
   if path==self.root and not changed:
    changed=True
    with open(self.root+'/late-file','wb') as f:f.write(b'late')
   return original(path,*a,**kw)
  with patch.object(g.os,'stat',side_effect=inspect):
   with self.assertRaises(RuntimeError):self.pre()

 def test_metadata_fault_is_redacted_and_has_no_displayed_exception_chain(self):
  with patch.object(g.os,'fstat',side_effect=OSError('synthetic-sensitive-path')):
   with self.assertRaisesRegex(RuntimeError,'^Storage admission held$') as found:self.pre()
  self.assertTrue(found.exception.__suppress_context__)
