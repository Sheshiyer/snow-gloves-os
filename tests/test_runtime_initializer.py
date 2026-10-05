"""Explicit fresh initialization checks with owned SQLite/HTTP child fixtures."""
import unittest,tempfile,pathlib,socket,sys,shutil,time,threading
from scripts.lib import runtime_initializer as module

class Review(unittest.TestCase):
 def setUp(self):
  self.parent=pathlib.Path(tempfile.mkdtemp(prefix='sg-init-review-')).resolve();self.data=self.parent/'data';self.data.mkdir(mode=0o700)
  self.fixture_path=self.parent/'fixture_child.py';self.fixture_path.write_text("import os,sqlite3,http.server\nc=sqlite3.connect(os.path.join(os.environ['DATA_DIR'],'storage.sqlite'));c.execute('create table owned_fixture(value text)');c.commit();c.close()\nclass Handler(http.server.BaseHTTPRequestHandler):\n def do_GET(self):\n  self.send_response(200 if self.path == '/healthz' else 404);self.send_header('Content-Length','3');self.end_headers();self.wfile.write(b'ok\\n')\n def log_message(self,*args):pass\nhttp.server.HTTPServer(('127.0.0.1',int(os.environ['PORT'])),Handler).serve_forever()\n")
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  self.supervisor=module.InitializingSupervisor(str(self.data),[sys.executable,str(self.fixture_path)],'synthetic-storage-fixture','synthetic-management-fixture',runtime_port=port)
 def tearDown(self):
  self.supervisor.stop();shutil.rmtree(self.parent)
 def test_actual_fresh_schema_http_without_admission(self):
  self.assertTrue(self.supervisor.initialize_fresh(authorized=True,timeout=1.5));self.assertFalse(self.supervisor.ready);self.assertTrue((self.data/'storage.sqlite').exists())
 def test_unauthorized_generic_no_spawn(self):
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=1)
  self.assertIsNone(self.supervisor.child_pid);self.assertEqual(list(self.data.iterdir()),[])
 def test_existing_state_generic_unchanged(self):
  p=self.data/'storage.sqlite';p.write_bytes(b'owned corrupt state')
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True)
  self.assertEqual(p.read_bytes(),b'owned corrupt state');self.assertIsNone(self.supervisor.child_pid)
 def test_invalid_timeout_generic_no_spawn(self):
  for timeout in [True,0,-1,float('inf'),float('nan'),121,'1']:
   with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,timeout=timeout)
  self.assertIsNone(self.supervisor.child_pid)
 def test_health_past_deadline_cannot_acknowledge_success(self):
  def delayed():time.sleep(0.2);return True
  self.supervisor._check_http_health=delayed
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,timeout=0.15)
  self.assertFalse(self.supervisor.ready)
 def test_second_initialization_denied_with_database_unchanged(self):
  self.assertTrue(self.supervisor.initialize_fresh(authorized=True,timeout=1.5));before=(self.data/'storage.sqlite').read_bytes()
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True)
  self.assertEqual((self.data/'storage.sqlite').read_bytes(),before)
 def test_interrupt_stops_owned_child_and_preserves_created_state(self):
  def interrupted():raise KeyboardInterrupt()
  self.supervisor._check_http_health=interrupted
  with self.assertRaises(KeyboardInterrupt):self.supervisor.initialize_fresh(authorized=True,timeout=1.5)
  self.assertIsNone(self.supervisor._child);self.assertTrue((self.data/'storage.sqlite').exists());self.assertFalse(self.supervisor.ready)
 def test_wrong_health_stops_owned_child_and_preserves_created_state(self):
  self.supervisor._check_http_health=lambda:False
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,timeout=0.2)
  self.assertIsNone(self.supervisor._child);self.assertTrue((self.data/'storage.sqlite').exists());self.assertFalse(self.supervisor.ready)
 def test_group_readable_root_denied_without_start(self):
  self.data.chmod(0o750)
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True)
  self.assertIsNone(self.supervisor.child_pid);self.assertEqual(list(self.data.iterdir()),[])
 def test_root_replaced_after_health_cannot_acknowledge_initialization(self):
  original=self.supervisor._check_http_health
  def changed_root():
   ready=original()
   if ready:
    old=self.parent/'data-original';self.data.rename(old);self.data.symlink_to(old,target_is_directory=True)
   return ready
  self.supervisor._check_http_health=changed_root
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,timeout=1.5)
  self.assertIsNone(self.supervisor._child);self.assertTrue((self.parent/'data-original/storage.sqlite').exists())
 def test_preexisting_cancellation_denied_without_spawn(self):
  event=threading.Event();event.set()
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,cancel_event=event)
  self.assertIsNone(self.supervisor.child_pid);self.assertEqual(list(self.data.iterdir()),[])
 def test_invalid_cancellation_type_denied_without_spawn(self):
  for value in [True,False,object(),1,'cancel']:
   with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,cancel_event=value)
  self.assertIsNone(self.supervisor.child_pid);self.assertEqual(list(self.data.iterdir()),[])
 def test_cancellation_stops_stalled_initialization_preserves_state(self):
  event=threading.Event();self.supervisor._check_http_health=lambda:False
  def cancel_after_state():
   deadline=time.monotonic()+2
   while not (self.data/'storage.sqlite').exists() and time.monotonic()<deadline:time.sleep(0.01)
   event.set()
  worker=threading.Thread(target=cancel_after_state);worker.start();start=time.monotonic()
  try:
   with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,timeout=10,cancel_event=event)
  finally:worker.join(3)
  self.assertLess(time.monotonic()-start,3);self.assertIsNone(self.supervisor.child_pid);self.assertTrue((self.data/'storage.sqlite').exists());self.assertFalse(self.supervisor.ready)
 def test_cancellation_at_health_cannot_acknowledge_success(self):
  event=threading.Event();original=self.supervisor._check_http_health
  def cancelled_health():
   ready=original()
   if ready:event.set()
   return ready
  self.supervisor._check_http_health=cancelled_health
  with self.assertRaisesRegex(RuntimeError,'^Runtime initialization failed$'):self.supervisor.initialize_fresh(authorized=True,timeout=1.5,cancel_event=event)
  self.assertIsNone(self.supervisor.child_pid);self.assertFalse(self.supervisor.ready)
if __name__=='__main__':unittest.main(verbosity=2)
