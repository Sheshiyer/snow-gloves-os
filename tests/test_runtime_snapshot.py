"""Bounded Linux snapshot WAL, quota, publication and ownership failure checks."""
import unittest,pathlib,tempfile,sqlite3,hashlib,os,shutil,stat,time,urllib.parse,sys
from unittest import mock
from scripts.lib.runtime_supervisor import Supervisor
from scripts.lib import runtime_snapshot as m

GENERIC='^Runtime snapshot failed$'
@unittest.skipUnless(sys.platform == "linux", "Linux root-descriptor confinement required")
class Review(unittest.TestCase):
 def setUp(self):
  self.parent=pathlib.Path(tempfile.mkdtemp(prefix='sg-snapshot-review-')).resolve();self.data=self.parent/'data';self.data.mkdir(mode=0o700);self.db=self.data/'storage.sqlite';self.writer=sqlite3.connect(self.db);self.writer.execute('pragma journal_mode=WAL');self.writer.execute('pragma wal_autocheckpoint=0');self.writer.execute('create table owned_fixture(value text)');self.writer.execute("insert into owned_fixture values('first')");self.writer.commit();self.writer.execute("insert into owned_fixture values('committed-WAL')");self.writer.commit();self.sup=Supervisor(str(self.data),['/usr/bin/true'],'s'*40,'m'*40);self.leaf='sg-snapshot-'+'1'*32+'.sqlite'
 def tearDown(self):self.writer.close();shutil.rmtree(self.parent)
 def call(self,**options):return m.write_bounded_snapshot(self.sup,self.leaf,**options)
 def test_real_committed_WAL_snapshot_hash_and_input_unchanged(self):
  before=self.db.read_bytes();wal_before=(self.data/'storage.sqlite-wal').read_bytes();result=self.call();artifact=self.data/self.leaf;c=sqlite3.connect('file:'+str(artifact)+'?mode=ro',uri=True);rows=c.execute('select value from owned_fixture order by rowid').fetchall();check=c.execute('pragma quick_check').fetchone()[0];c.close();self.assertEqual(rows,[('first',),('committed-WAL',)]);self.assertEqual(check,'ok');self.assertEqual(result,{'leaf':self.leaf,'bytes':artifact.stat().st_size,'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()});self.assertEqual(stat.S_IMODE(artifact.stat().st_mode),0o600);self.assertEqual(artifact.stat().st_nlink,1);self.assertEqual(self.db.read_bytes(),before);self.assertEqual((self.data/'storage.sqlite-wal').read_bytes(),wal_before)
 def test_existing_output_unchanged(self):
  p=self.data/self.leaf;p.write_bytes(b'owned unrelated artifact')
  with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
  self.assertEqual(p.read_bytes(),b'owned unrelated artifact')
 def test_logical_quota_rejected_without_artifact(self):
  with self.assertRaisesRegex(RuntimeError,GENERIC):self.call(max_bytes=4096)
  self.assertFalse((self.data/self.leaf).exists());self.assertFalse(any(x.name.startswith('.sg-snapshot-work-') for x in self.data.iterdir()))
 def test_invalid_limits_generic(self):
  for value in [True,0,-1,67108865,'1']:
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call(max_bytes=value)
 def test_huge_timeout_generic(self):
  with self.assertRaisesRegex(RuntimeError,GENERIC):self.call(timeout=10**1000)
 def test_file_fsync_failure_no_publication_or_owned_temp(self):
  original=os.fsync
  def denied(fd):
   if stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('owned injected file fsync')
   return original(fd)
  with mock.patch.object(m.os,'fsync',side_effect=denied):
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
  self.assertFalse((self.data/self.leaf).exists());self.assertFalse(any(x.name.startswith('.sg-snapshot-work-') for x in self.data.iterdir()))
 def test_directory_fsync_failure_no_success_preserves_output(self):
  original=os.fsync
  def denied(fd):
   if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('owned injected directory fsync')
   return original(fd)
  with mock.patch.object(m.os,'fsync',side_effect=denied):
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
  self.assertTrue((self.data/self.leaf).exists())
 def test_same_inode_byte_replacement_before_link_no_success(self):
  original=os.link
  def changed(src,dst,**options):
   fd=os.open(src,os.O_WRONLY,dir_fd=options['src_dir_fd']);os.pwrite(fd,b'changed-bytes',512);os.close(fd);return original(src,dst,**options)
  with mock.patch.object(m.os,'link',side_effect=changed):
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
 def test_root_moved_after_preflight_no_success(self):
  original=os.link
  def moved(src,dst,**options):
   old=self.parent/'original-data';self.data.rename(old);self.data.symlink_to(old,target_is_directory=True);return original(src,dst,**options)
  with mock.patch.object(m.os,'link',side_effect=moved):
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
 def test_unexpected_temp_sidecar_holds_without_deleting_unknown(self):
  original=os.fsync;created=[]
  def extra(fd):
   if stat.S_ISREG(os.fstat(fd).st_mode) and not created:
    name=os.readlink('/proc/self/fd/'+str(fd))+'-wal';p=pathlib.Path(name);p.write_bytes(b'owned unknown sidecar');created.append(p)
   return original(fd)
  with mock.patch.object(m.os,'fsync',side_effect=extra):
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
  self.assertEqual(len(created),1);self.assertEqual(created[0].read_bytes(),b'owned unknown sidecar')
 def test_replaced_temp_alias_cannot_mutate_owned_foreign_database(self):
  foreign=self.parent/'foreign.sqlite';c=sqlite3.connect(foreign);c.execute('create table foreign_fixture(value text)');c.commit();c.close();before=foreign.read_bytes();original=sqlite3.connect;swapped=[]
  def intercepted(database,*args,**kwargs):
   if 'mode=rw' in str(database) and 'mode=ro' not in str(database) and not swapped:
    location=urllib.parse.unquote(urllib.parse.urlparse(str(database)).path);p=pathlib.Path(os.readlink(location)) if location.rsplit('/',1)[-1].isdigit() else pathlib.Path(location);p.rename(self.data/'preserved-original-temp');p.symlink_to(foreign);swapped.append(True)
   return original(database,*args,**kwargs)
  with mock.patch.object(m.sqlite3,'connect',side_effect=intercepted):
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
  self.assertEqual(foreign.read_bytes(),before)
 def test_missing_source_is_not_created(self):
  self.writer.close();self.db.unlink()
  with self.assertRaisesRegex(RuntimeError,GENERIC):self.call()
  self.assertFalse(self.db.exists())
 def test_source_growth_during_online_backup_exceeds_quota_and_is_held(self):
  self.writer.execute('create table payloads(data blob)');self.writer.execute('insert into payloads values(?)',(b'a'*100000,));self.writer.commit();original=sqlite3.connect;grew=[]
  class Proxy:
   def __init__(proxy,connection):proxy.connection=connection
   def __getattr__(proxy,name):return getattr(proxy.connection,name)
   def backup(proxy,destination,*,pages,progress,**options):
    def observed(status,remaining,total):
     if status==sqlite3.SQLITE_OK and not grew:
      self.writer.execute('insert into payloads values(?)',(b'b'*400000,));self.writer.commit();grew.append(True)
     progress(status,remaining,total)
    return proxy.connection.backup(destination,pages=pages,progress=observed,**options)
  def wrapped(database,*args,**kwargs):
   connection=original(database,*args,**kwargs)
   return Proxy(connection) if 'storage.sqlite' in str(database) and 'mode=ro' in str(database) else connection
  with mock.patch.object(m.sqlite3,'connect',side_effect=wrapped):
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call(max_bytes=262144)
  self.assertEqual(grew,[True]);self.assertFalse((self.data/self.leaf).exists())
 def test_busy_sqlite_source_deadline_is_held(self):
  self.writer.execute('pragma journal_mode=DELETE');self.writer.execute('begin exclusive');started=time.monotonic()
  try:
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call(timeout=0.1)
  finally:self.writer.rollback()
  self.assertLess(time.monotonic()-started,0.5);self.assertFalse((self.data/self.leaf).exists())
 def test_held_supervisor_lock_has_bounded_deadline_before_files(self):
  self.sup._lock.acquire();started=time.monotonic()
  try:
   with self.assertRaisesRegex(RuntimeError,GENERIC):self.call(timeout=0.05)
  finally:self.sup._lock.release()
  self.assertLess(time.monotonic()-started,0.2);self.assertFalse((self.data/self.leaf).exists());self.assertFalse(any(x.name.startswith('.sg-snapshot-work-') for x in self.data.iterdir()))
if __name__=='__main__':unittest.main(verbosity=2)
