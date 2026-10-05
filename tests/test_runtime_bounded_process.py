import unittest,sys,importlib.util,time,os
import lib.runtime_bounded_process as m
@unittest.skipUnless(sys.platform == "linux", "Linux owned process groups required")
class Review(unittest.TestCase):
 def run_child(self,code,**kwargs):return m.run_bounded([sys.executable,'-c',code],{},**kwargs)
 def test_valid_output(self):self.assertEqual(self.run_child("print('owned')"),b'owned\n')
 def test_nonzero_held(self):
  with self.assertRaises(RuntimeError):self.run_child("print('owned');raise SystemExit(7)")
 def test_stderr_held(self):
  with self.assertRaises(RuntimeError):self.run_child("import sys;print('owned');print('fixture stderr',file=sys.stderr)")
 def test_flood_held(self):
  with self.assertRaises(RuntimeError):self.run_child("import os;os.write(1,b'x'*1000000)",max_output=1024)
 def test_timeout_held(self):
  start=time.monotonic()
  with self.assertRaises(RuntimeError):self.run_child("import time;time.sleep(10)",timeout=0.1)
  self.assertLess(time.monotonic()-start,1)
 def test_no_success_without_output(self):
  with self.assertRaises(RuntimeError):self.run_child('pass')
 def test_inherited_pipe_descendant_deadline(self):
  start=time.monotonic()
  with self.assertRaises(RuntimeError):self.run_child("import os,time;pid=os.fork();time.sleep(10) if pid==0 else print('parent')",timeout=0.1)
  self.assertLess(time.monotonic()-start,1)
 def test_invalid_inputs_no_process(self):
  from unittest.mock import patch
  cases=[([],{},15,4096),([sys.executable],{'bad=key':'x'},15,4096),([sys.executable],{},float('nan'),4096),([sys.executable],{},True,4096),([sys.executable],{},15,True)]
  for argv,env,timeout,limit in cases:
   with self.subTest(argv=argv,env=env,timeout=timeout,limit=limit),patch.object(m.subprocess,'Popen') as launch:
    with self.assertRaisesRegex(RuntimeError,'^Bounded process held$'):m.run_bounded(argv,env,timeout,limit)
    launch.assert_not_called()
 def test_owned_descendant_removed_after_timeout(self):
  import tempfile,pathlib
  with tempfile.TemporaryDirectory() as directory:
   path=pathlib.Path(directory)/'owned-pid'
   code="import os,time,pathlib;pid=os.fork();time.sleep(10) if pid==0 else (pathlib.Path("+repr(str(path))+").write_text(str(pid)),print('owned parent'))"
   with self.assertRaises(RuntimeError):self.run_child(code,timeout=0.3)
   pid=int(path.read_text());deadline=time.monotonic()+1
   while time.monotonic()<deadline:
    try:os.kill(pid,0)
    except ProcessLookupError:break
    time.sleep(0.01)
   with self.assertRaises(ProcessLookupError):os.kill(pid,0)
if __name__=='__main__':unittest.main(verbosity=2)
