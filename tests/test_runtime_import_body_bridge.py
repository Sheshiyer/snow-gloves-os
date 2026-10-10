"""Owned, bounded real socketpair verification; every child must prove its result."""
from pathlib import Path
import json,os,signal,subprocess,sys
import pytest
SOURCE=Path(__file__).resolve().parents[1]/'scripts/lib/runtime_import_body_bridge.py'
STREAM_CHILD = r"""import importlib.util,os,socket,threading,time,hashlib,json,fcntl,select
spec=importlib.util.spec_from_file_location('bridge_candidate',__SG_BRIDGE_SOURCE__);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def exercise(mode,total):
 a,b=socket.socketpair();b.settimeout(2 if total>1000000 and mode in ('cold','replay') else .5);event=threading.Event();block=b'a'*65536;digest=hashlib.sha256();left=total
 while left:digest.update(block[:min(left,65536)]);left-=min(left,65536)
 sha=digest.hexdigest();negative=mode in ('zero','wrong','early','trailer','cancel','slow','backpressure');budget=.3 if negative else (14 if total>1000000 else 2)
 if mode=='kernel':
  a.settimeout(None);fcntl.fcntl(a.fileno(),fcntl.F_SETFL,fcntl.fcntl(a.fileno(),fcntl.F_GETFL)|os.O_NONBLOCK)
 timeout=a.gettimeout();flags=fcntl.fcntl(a.fileno(),fcntl.F_GETFL);bridge=m.ImportBodyBridge(a,total,'0'*64 if mode=='wrong' else sha,event,time.monotonic()+budget);reader=None;sender=None;errors=[];received=0;got=hashlib.sha256();original_write=m.os.write
 def send():
  try:
   left=total//2 if mode=='early' else total
   while left:
    n=min(left,65536);b.sendall(block[:n]);left-=n
    if mode=='slow':time.sleep(.4)
    if mode=='cancel':event.set();break
   b.shutdown(socket.SHUT_WR)
  except Exception as e:errors.append(type(e).__name__)
 try:
  if mode=='trailer':b.sendall(block[:total]+b'X');b.shutdown(socket.SHUT_WR)
  reader=bridge.start();identity=m._safe_fstat(reader)
  if mode in ('partial','zero'):
   writer=bridge._pipe_w
   def write(fd,data):
    if fd==writer:return 0 if mode=='zero' else original_write(fd,data[:31])
    return original_write(fd,data)
   m.os.write=write
  if mode!='trailer':sender=threading.Thread(target=send);sender.start()
  if mode not in ('replay','backpressure'):
   end=time.monotonic()+budget+1
   while time.monotonic()<end:
    try:chunk=os.read(reader,65536)
    except BlockingIOError:select.select([reader],[],[],.01);continue
    if not chunk:break
    received+=len(chunk);got.update(chunk)
   else:raise AssertionError('owned drain exceeded bound')
  try:summary=bridge.finish(verified_replay=mode=='replay');state=summary['state']
  except RuntimeError as error:assert str(error)=='Import body bridge held';state='held';summary=None
  assert state==('held' if negative else 'body-verified'),(mode,state,type(bridge._producer_error).__name__,str(bridge._producer_error),bridge._cleanup_fault,bridge._writer_closed_ok,bridge._dup_closed_ok)
  if not negative:
   assert summary=={'schema':'sg.local-import-body-bridge.v1','state':'body-verified','bytes':total,'sha256':sha,'replay_discard':mode=='replay'}
   if mode!='replay':assert received==total and got.hexdigest()==sha
   assert bridge.worker_quiescent is True
   assert a.gettimeout()==timeout and fcntl.fcntl(a.fileno(),fcntl.F_GETFL)==flags
   assert m._safe_fstat(reader)!=identity
 finally:
  m.os.write=original_write;event.set()
  try:bridge.abort()
  except RuntimeError:pass
  try:b.shutdown(socket.SHUT_RDWR)
  except OSError:pass
  b.close()
  if sender is not None:sender.join(1);assert not sender.is_alive()
  assert bridge.worker_quiescent is True,(mode,"fixture cleanup not quiescent",bridge._worker_thread.is_alive(),bridge._fault,bridge._cleanup_fault)
  if reader is not None and m._safe_fstat(reader)==identity:os.close(reader)
  a.close()
 if not negative:assert not errors,errors
 return {'mode':mode,'bytes':total,'state':state,'received':received}
"""
OWNERSHIP_CHILD = r"""import importlib.util,os,socket,threading,time,hashlib,json
spec=importlib.util.spec_from_file_location('bridge_candidate',__SG_BRIDGE_SOURCE__);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
a,b=socket.socketpair();event=threading.Event();payload=b'owned-body-fixture'*16;sha=hashlib.sha256(payload).hexdigest()
"""
CASES=[
('cold-large', STREAM_CHILD + r"""
print(json.dumps(exercise('cold',13631488)))""", 20, {'mode': 'cold', 'bytes': 13631488, 'state': 'body-verified'}, True),
('replay-large', STREAM_CHILD + r"""
print(json.dumps(exercise('replay',13631488)))""", 20, {'mode': 'replay', 'bytes': 13631488, 'state': 'body-verified'}, True),
('cold-small', STREAM_CHILD + r"""
print(json.dumps(exercise('cold',512)))""", 3, {'mode': 'cold', 'bytes': 512, 'state': 'body-verified'}, True),
('partial-write', STREAM_CHILD + r"""
print(json.dumps(exercise('partial',8192)))""", 3, {'mode': 'partial', 'bytes': 8192, 'state': 'body-verified'}, True),
('zero-write', STREAM_CHILD + r"""
print(json.dumps(exercise('zero',512)))""", 3, {'mode': 'zero', 'bytes': 512, 'state': 'held'}, True),
('wrong-sha', STREAM_CHILD + r"""
print(json.dumps(exercise('wrong',512)))""", 3, {'mode': 'wrong', 'bytes': 512, 'state': 'held'}, True),
('early-eof', STREAM_CHILD + r"""
print(json.dumps(exercise('early',512)))""", 3, {'mode': 'early', 'bytes': 512, 'state': 'held'}, True),
('queued-trailer', STREAM_CHILD + r"""
print(json.dumps(exercise('trailer',512)))""", 3, {'mode': 'trailer', 'bytes': 512, 'state': 'held'}, True),
('midstream-cancel', STREAM_CHILD + r"""
print(json.dumps(exercise('cancel',512)))""", 3, {'mode': 'cancel', 'bytes': 512, 'state': 'held'}, True),
('slow-body', STREAM_CHILD + r"""
print(json.dumps(exercise('slow',131072)))""", 3, {'mode': 'slow', 'bytes': 131072, 'state': 'held'}, True),
('backpressure', STREAM_CHILD + r"""
print(json.dumps(exercise('backpressure',1048576)))""", 3, {'mode': 'backpressure', 'bytes': 1048576, 'state': 'held'}, True),
('kernel-inconsistent', STREAM_CHILD + r"""
print(json.dumps(exercise('kernel',8192)))""", 3, {'mode': 'kernel', 'bytes': 8192, 'state': 'body-verified'}, True),
('positive', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);result=bridge.finish(verified_replay=True);print(json.dumps({'state':result['state'],'quiescent':bridge.worker_quiescent}));a.close();b.close()
""", 3, {'state': 'body-verified', 'quiescent': True}, False),
('wrong_sha_reader_cleanup', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),'a'*64,event,time.monotonic()+.4);reader=bridge.start();identity=m._safe_fstat(reader);b.sendall(payload);assert bridge._producer_done.wait(.3)
try:bridge.finish();reported='ack'
except RuntimeError:reported='held'
opened=m._safe_fstat(reader)==identity;print(json.dumps({'reported':reported,'owned_reader_still_open':opened}));bridge.abort();a.close();b.close()
""", 3, {'reported': 'held', 'owned_reader_still_open': False}, False),
('writer_close_denial', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);original=m._close_fd_no_retry
def fail(fd):
 if fd==bridge._pipe_w:return False
 return original(fd)
m._close_fd_no_retry=fail;reader=bridge.start();writer=bridge._pipe_w;b.sendall(payload);assert bridge._producer_done.wait(.3)
try:bridge.finish(verified_replay=True);reported='ack'
except RuntimeError:reported='held'
m._close_fd_no_retry=original
try:bridge.abort()
except RuntimeError:pass

if m._safe_fstat(writer)==bridge._pipe_w_stat:os.close(writer)
print(json.dumps({'reported':reported}));a.close();b.close()
""", 3, {'reported': 'held'}, False),
('late_cleanup_denial', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.15);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.1);original=bridge._restore_socket_flags
def late():
 time.sleep(.2);return original()
bridge._restore_socket_flags=late
try:bridge.finish(verified_replay=True);reported='ack'
except RuntimeError:reported='held'
print(json.dumps({'reported':reported,'expired':time.monotonic()>=bridge._deadline}));a.close();b.close()
""", 3, {'reported': 'held', 'expired': True}, False),
('start_before_launch_leak', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);original=m.threading.Thread.start
def fail(self):raise RuntimeError('synthetic start fault')
m.threading.Thread.start=fail
try:bridge.start();reported='started'
except RuntimeError:reported='held'
m.threading.Thread.start=original;writer=bridge._pipe_w;dup=bridge._sock_dup_fd;opened=m._safe_fstat(writer)==bridge._pipe_w_stat and m._safe_fstat(dup)==bridge._sock_dup_stat;print(json.dumps({'reported':reported,'writer_dup_open':opened,'quiescent':bridge.worker_quiescent}));
if writer is not None and m._safe_fstat(writer)==bridge._pipe_w_stat:os.close(writer)
if dup is not None and m._safe_fstat(dup)==bridge._sock_dup_stat:os.close(dup)
a.close();b.close()
""", 3, {'reported': 'held', 'writer_dup_open': False, 'quiescent': True}, False),
('join_exception_false_ack', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3)
def fail(*args,**kwargs):raise RuntimeError('synthetic join fault')
bridge._worker_thread.join=fail
try:result=bridge.finish(verified_replay=True);reported=result['state']
except RuntimeError:reported='held'
print(json.dumps({'reported':reported}));a.close();b.close()
""", 3, {'reported': 'held'}, False),
('uncertain_start_live_worker', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);release=threading.Event();entered=threading.Event();original_start=m.threading.Thread.start;original_alive=m.threading.Thread.is_alive;captured={}
def parked():entered.set();release.wait(1)
bridge._producer_loop=parked
def launched_then_raise(self):
 captured['writer']=bridge._pipe_w;captured['identity']=bridge._pipe_w_stat;original_start(self);assert entered.wait(.2);raise RuntimeError('after launch')
def uncertain(self):raise RuntimeError('observer failed')
m.threading.Thread.start=launched_then_raise;m.threading.Thread.is_alive=uncertain
try:bridge.start();reported='started'
except RuntimeError:reported='held'
m.threading.Thread.start=original_start;m.threading.Thread.is_alive=original_alive;live=bridge._worker_thread.is_alive();quiescent=bridge.worker_quiescent;closed=m._safe_fstat(captured['writer'])!=captured['identity'];print(json.dumps({'reported':reported,'actual_worker_alive':live,'reported_quiescent':quiescent,'writer_closed_under_live_worker':closed}));release.set();bridge._worker_thread.join(.5)
try:bridge.abort()
except RuntimeError:pass

for fd,identity in [(bridge._pipe_w,bridge._pipe_w_stat),(bridge._sock_dup_fd,bridge._sock_dup_stat)]:
 if fd is not None and m._safe_fstat(fd)==identity:os.close(fd)
a.close();b.close()
""", 3, {'reported': 'held', 'actual_worker_alive': True, 'reported_quiescent': False, 'writer_closed_under_live_worker': False}, False),
('original_interrupt_masked', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);original_cleanup=bridge._contained_cleanup;interrupt=KeyboardInterrupt('owned fixture interrupt')
def join_interrupt(*args,**kwargs):raise interrupt
def cleanup_fault(*args,**kwargs):raise RuntimeError('owned fixture cleanup failure')
bridge._worker_thread.join=join_interrupt;bridge._contained_cleanup=cleanup_fault
try:bridge.finish();reported='ack';same=False
except BaseException as error:reported=type(error).__name__;same=error is interrupt
bridge._contained_cleanup=original_cleanup;bridge.abort();print(json.dumps({'reported':reported,'original_interrupt_preserved':same}));a.close();b.close()
""", 3, {'reported': 'KeyboardInterrupt', 'original_interrupt_preserved': True}, False),
('borrowed_replacement_preserved', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);spare,writer=os.pipe();os.dup2(spare,reader);os.close(spare);identity=m._safe_fstat(reader);flags=m.fcntl.fcntl(reader,m.fcntl.F_GETFL)
try:bridge.finish();reported='ack'
except RuntimeError:reported='held'
assert reported=='held' and m._safe_fstat(reader)==identity and m.fcntl.fcntl(reader,m.fcntl.F_GETFL)==flags;os.close(reader);os.close(writer);a.close();b.close();print(json.dumps({'reported':reported,'replacement_preserved':True}))
""", 3, {'reported': 'held', 'replacement_preserved': True}, False),
('original_socket_replacement_preserved', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);replacement=os.open(os.devnull,os.O_RDWR);os.dup2(replacement,a.fileno());os.close(replacement);identity=m._safe_fstat(a.fileno());flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:bridge.finish();reported='ack'
except RuntimeError:reported='held'
assert reported=='held' and m._safe_fstat(a.fileno())==identity and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':reported,'replacement_preserved':True}))
""", 3, {'reported': 'held', 'replacement_preserved': True}, False),
('constructor_chained_clock_redaction', OWNERSHIP_CHILD + r"""deadline=time.monotonic()+.4;original=m.time.monotonic
def boom():
 try:raise ValueError('synthetic hidden diagnostic')
 except ValueError as cause:raise RuntimeError('Import body bridge held') from cause
m.time.monotonic=boom
try:m.ImportBodyBridge(a,len(payload),sha,event,deadline);reported='ack'
except RuntimeError as error:reported='held';held=error
m.time.monotonic=original;import traceback;rendered=''.join(traceback.format_exception(held));assert reported=='held' and held.__suppress_context__ and 'synthetic hidden diagnostic' not in rendered;a.close();b.close();print(json.dumps({'reported':reported,'diagnostic_suppressed':True}))
""", 3, {'reported': 'held', 'diagnostic_suppressed': True}, False),
('partial_start_replacement_preserved', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);spare,writer=os.pipe();original_dup=m.os.dup;original_fcntl=m.fcntl.fcntl;owned={}
def dup(fd):
 result=original_dup(fd);owned['fd']=result;return result
def flags(fd,cmd,*args):
 if fd==owned.get('fd') and cmd==m.fcntl.F_SETFD:
  os.dup2(spare,fd);owned['identity']=m._safe_fstat(fd);raise RuntimeError('owned partial start fault')
 return original_fcntl(fd,cmd,*args)
m.os.dup=dup;m.fcntl.fcntl=flags
try:bridge.start();reported='started'
except RuntimeError:reported='held'
m.os.dup=original_dup;m.fcntl.fcntl=original_fcntl;assert reported=='held' and m._safe_fstat(owned['fd'])==owned['identity'];os.close(owned['fd']);os.close(spare);os.close(writer);a.close();b.close();print(json.dumps({'reported':reported,'replacement_preserved':True}))
""", 3, {'reported': 'held', 'replacement_preserved': True}, False),
('original_systemexit_preserved', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);original_cleanup=bridge._contained_cleanup;interrupt=SystemExit(42)
def join_interrupt(*args,**kwargs):raise interrupt
def cleanup_fault(*args,**kwargs):raise RuntimeError('owned fixture cleanup failure')
bridge._worker_thread.join=join_interrupt;bridge._contained_cleanup=cleanup_fault
try:bridge.finish();reported='ack';same=False
except BaseException as error:reported=type(error).__name__;same=error is interrupt
bridge._contained_cleanup=original_cleanup;bridge.abort();print(json.dumps({'reported':reported,'original_interrupt_preserved':same}));a.close();b.close()
""", 3, {'reported': 'SystemExit', 'original_interrupt_preserved': True}, False),
('finish_cleanup_diagnostic_leak', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);original_cleanup=bridge._contained_cleanup
def boom(*args,**kwargs):
 try:raise ValueError('synthetic hidden cleanup diagnostic')
 except ValueError as cause:raise RuntimeError('synthetic exposed cleanup diagnostic') from cause
bridge._contained_cleanup=boom
try:bridge.finish();reported='ack';leaked=False
except RuntimeError as error:
 import traceback;reported=str(error);leaked='synthetic hidden cleanup diagnostic' in ''.join(traceback.format_exception(error))
bridge._contained_cleanup=original_cleanup
try:bridge.abort()
except RuntimeError:pass
a.close();b.close();print(json.dumps({'reported':reported,'hidden_diagnostic_leaked':leaked}))
""", 3, {'reported': 'Import body bridge held', 'hidden_diagnostic_leaked': False}, False),
('abort_original_interrupt_masked', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);original_set=event.set;original_cleanup=bridge._contained_cleanup;interrupt=KeyboardInterrupt('owned original abort interrupt')
def boom_set():raise interrupt
def boom_cleanup(*args,**kwargs):raise RuntimeError('owned cleanup fault')
event.set=boom_set;bridge._contained_cleanup=boom_cleanup
try:bridge.abort();reported='returned';same=False
except BaseException as error:reported=type(error).__name__;same=error is interrupt
event.set=original_set;bridge._contained_cleanup=original_cleanup
try:bridge.abort()
except RuntimeError:pass
a.close();b.close();print(json.dumps({'reported':reported,'original_interrupt_preserved':same}))
""", 3, {'reported': 'KeyboardInterrupt', 'original_interrupt_preserved': True}, False),
('producer_close_interrupt', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);original_close=m._close_fd_no_retry
def close_interrupt(fd):
 if fd==bridge._pipe_w:raise KeyboardInterrupt('synthetic owned close interrupt')
 return original_close(fd)
m._close_fd_no_retry=close_interrupt;reader=bridge.start();writer=bridge._pipe_w;writer_id=bridge._pipe_w_stat;dup=bridge._sock_dup_fd;dup_id=bridge._sock_dup_stat;b.sendall(payload);bridge._worker_thread.join(.3);assert not bridge._worker_thread.is_alive()
try:bridge.finish();reported='ack'
except RuntimeError:reported='held'
m._close_fd_no_retry=original_close;writer_open=m._safe_fstat(writer)==writer_id;dup_open=m._safe_fstat(dup)==dup_id
if writer_open:os.close(writer)
if dup_open:os.close(dup)
try:bridge.abort()
except RuntimeError:pass
a.close();b.close();print(json.dumps({'reported':reported,'owned_writer_open':writer_open,'owned_dup_open':dup_open}))
""", 3, {'reported': 'held', 'owned_writer_open': True, 'owned_dup_open': False}, False),
('finish_clock_diagnostic_leak', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);reader=bridge.start();b.sendall(payload);assert bridge._producer_done.wait(.3);original_clock=m.time.monotonic
def clock_fault():
 try:raise ValueError('synthetic hidden clock diagnostic')
 except ValueError as cause:raise RuntimeError('synthetic exposed clock diagnostic') from cause
m.time.monotonic=clock_fault
try:bridge.finish();reported='ack';leaked=False
except RuntimeError as error:
 import traceback;reported=str(error);leaked='synthetic hidden clock diagnostic' in ''.join(traceback.format_exception(error))
m.time.monotonic=original_clock
try:bridge.abort()
except RuntimeError:pass
a.close();b.close();print(json.dumps({'reported':reported,'hidden_diagnostic_leaked':leaked}))
""", 3, {'reported': 'Import body bridge held', 'hidden_diagnostic_leaked': False}, False),
('start_original_interrupt_masked', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);interrupt=KeyboardInterrupt('owned original start interrupt');original_start=m.threading.Thread.start;original_reconcile=bridge._reconcile_and_contain_failed_start
def start_interrupt(*args,**kwargs):raise interrupt
def reconcile_fault(*args,**kwargs):raise RuntimeError('owned reconcile fault')
m.threading.Thread.start=start_interrupt;bridge._reconcile_and_contain_failed_start=reconcile_fault
try:bridge.start();reported='returned';same=False
except BaseException as error:reported=type(error).__name__;same=error is interrupt
m.threading.Thread.start=original_start;bridge._reconcile_and_contain_failed_start=original_reconcile;original_reconcile(bridge._worker_thread,False);a.close();b.close();print(json.dumps({'reported':reported,'original_interrupt_preserved':same}))
""", 3, {'reported': 'KeyboardInterrupt', 'original_interrupt_preserved': True}, False),
('start_cleanup_clock_diagnostic', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);original_start=m.threading.Thread.start;original_clock=m.time.monotonic
def clock_fault():
 try:raise ValueError('synthetic hidden startup clock diagnostic')
 except ValueError as cause:raise RuntimeError('synthetic exposed startup clock diagnostic') from cause
def start_fault(*args,**kwargs):m.time.monotonic=clock_fault;raise RuntimeError('owned start failure')
m.threading.Thread.start=start_fault
try:bridge.start();reported='ack';leaked=False
except RuntimeError as error:
 import traceback;reported=str(error);leaked='synthetic hidden startup clock diagnostic' in ''.join(traceback.format_exception(error))
m.threading.Thread.start=original_start;m.time.monotonic=original_clock;bridge._contained_cleanup();a.close();b.close();print(json.dumps({'reported':reported,'hidden_diagnostic_leaked':leaked}))
""", 3, {'reported': 'Import body bridge held', 'hidden_diagnostic_leaked': False}, False),
('constructor_lock_diagnostic', OWNERSHIP_CHILD + r"""deadline=time.monotonic()+.4;original_lock=m.threading.Lock
def lock_fault():
 try:raise ValueError('synthetic hidden lock diagnostic')
 except ValueError as cause:raise RuntimeError('synthetic exposed lock diagnostic') from cause
m.threading.Lock=lock_fault
try:m.ImportBodyBridge(a,len(payload),sha,event,deadline);reported='ack';leaked=False
except RuntimeError as error:
 import traceback;reported=str(error);leaked='synthetic hidden lock diagnostic' in ''.join(traceback.format_exception(error))
m.threading.Lock=original_lock;a.close();b.close();print(json.dumps({'reported':reported,'hidden_diagnostic_leaked':leaked}))
""", 3, {'reported': 'Import body bridge held', 'hidden_diagnostic_leaked': False}, False),
('dup_original_race_mutation', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);replacement,peer=socket.socketpair();flags=m.fcntl.fcntl(replacement.fileno(),m.fcntl.F_GETFL);original_dup=m.os.dup
def swap_then_dup(fd):
 os.dup2(replacement.fileno(),fd);return original_dup(fd)
m.os.dup=swap_then_dup
try:bridge.start();reported='started'
except RuntimeError:reported='held'
m.os.dup=original_dup
try:bridge.abort()
except RuntimeError:pass
mutated=m.fcntl.fcntl(replacement.fileno(),m.fcntl.F_GETFL)!=flags;replacement.close();peer.close();a.close();b.close();print(json.dumps({'reported':reported,'replacement_flags_mutated':mutated}))
""", 3, {'reported': 'held', 'replacement_flags_mutated': False}, False),
('forwarding_buffer_identity', OWNERSHIP_CHILD + r"""bridge=m.ImportBodyBridge(a,len(payload),sha,event,time.monotonic()+.4);original_read=m.os.read;original_write=m.os.write;last={};seen=[]
def read(fd,n):
 data=original_read(fd,n)
 if fd==bridge._sock_dup_fd:last['chunk']=data;assert n<=65536
 return data
def write(fd,data):
 if fd==bridge._pipe_w:
  seen.append(type(data).__name__);assert isinstance(data,memoryview) and data.obj is last['chunk'];return original_write(fd,data[:31])
 return original_write(fd,data)
m.os.read=read;m.os.write=write;reader=bridge.start();b.sendall(payload)
while True:
 try:chunk=os.read(reader,65536)
 except BlockingIOError:time.sleep(.001);continue
 if not chunk:break
try:bridge.finish();reported='body-verified'
except RuntimeError:reported='held'
m.os.read=original_read;m.os.write=original_write
try:bridge.abort()
except RuntimeError:pass
a.close();b.close();print(json.dumps({'reported':reported,'write_input_types':sorted(set(seen))}))
""", 3, {'reported': 'body-verified', 'write_input_types': ['memoryview']}, False),
('bool_bytes', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,True,sha,event,time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('float_bytes', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1.0,sha,event,time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('subclass_bytes', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,N(1),sha,event,time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('zero_bytes', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,0,sha,event,time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('too_large_bytes', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,64*1024*1024+4137,sha,event,time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('sha_subclass', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,S(sha),event,time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('upper_sha', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,'A'*64,event,time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('event_subclass', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,sha,E(),time.monotonic()+.4);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('nan_deadline', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,sha,event,float('nan'));reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('inf_deadline', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,sha,event,float('inf'));reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('bool_deadline', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,sha,event,True);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('stale_deadline', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,sha,event,time.monotonic()-.1);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
('beyond_deadline', OWNERSHIP_CHILD + r"""
class N(int):pass
class S(str):pass
class E(threading.Event):pass

calls=[]
def effect(*args,**kwargs):calls.append(True);raise AssertionError('constructor effect')
m.os.pipe=effect;m.os.dup=effect
if hasattr(m.os,'pipe2'):m.os.pipe2=effect
flags=m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)
try:m.ImportBodyBridge(a,1,sha,event,time.monotonic()+16);reported='ack'
except RuntimeError as error:assert str(error)=='Import body bridge held';reported='held'
assert reported=='held' and calls==[] and m.fcntl.fcntl(a.fileno(),m.fcntl.F_GETFL)==flags;a.close();b.close();print(json.dumps({'reported':'held','allocation_effects':0}))
""", 3, {'reported': 'held', 'allocation_effects': 0}, False),
]
@pytest.mark.parametrize('name,code,timeout,expected,subset',CASES,ids=[case[0] for case in CASES])
def test_owned_body_bridge(name,code,timeout,expected,subset):
    # The child imports only the candidate in this checkout; -I ignores inherited paths.
    code=code.replace('__SG_BRIDGE_SOURCE__',repr(str(SOURCE)))
    proc=subprocess.Popen([sys.executable,'-I','-B','-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,env={'PATH':'/usr/bin:/bin:/opt/homebrew/bin'})
    try:
        out,err=proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.communicate(timeout=2)
        pytest.fail('owned child exceeded its bound')
    assert proc.returncode==0,(name,out,err)
    assert err=='',(name,err)
    result=json.loads(out)
    if subset:assert all(result.get(key)==value for key,value in expected.items()),(name,result)
    else:assert result==expected,(name,result)
