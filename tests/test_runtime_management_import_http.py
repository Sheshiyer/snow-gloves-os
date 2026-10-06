"""Owned child-process framed HTTP import contract checks."""
from pathlib import Path
import json,os,signal,subprocess,sys
import pytest
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
def _run(program,case):
    proc=subprocess.Popen([sys.executable,'-I','-B','-c',program,str(SCRIPTS),case],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,env={'PATH':os.environ.get('PATH','/usr/bin:/bin')})
    try:
        stdout,stderr=proc.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid,signal.SIGKILL)
        proc.communicate(timeout=2)
        pytest.fail('Owned HTTP probe timed out')
    assert proc.returncode==0,stderr
    assert stderr==''
    return json.loads(stdout)
HTTP_CHILD=r'''import sys,json,hashlib,socket,threading,select,os
sys.path.insert(0,sys.argv[1]);import lib.runtime_management_http as mod
from lib.runtime_operation_identity import checkpoint_digest
from lib.runtime_import_request_registry import ImportRequestRegistry
case=sys.argv[2];data=b'OWNED-HTTP-CIPHER';ctx={'instanceId':'inst-1','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'key-1'};job='b'*32;req=checkpoint_digest(ctx,job);art={'leaf':'sg-encrypted-'+job+'.bin','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()};rec={'schema':'sg.local-job.v1','job_id':job,'request_digest':req,'state':'artifact-verified','artifact':dict(art)};prefix=f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/{job}/{req}/{art['sha256']}";receipt={'schema':'sg.remote-checkpoint.v1','state':'remote-committed','context':dict(ctx),'job_id':job,'request_digest':req,'artifact':dict(art),'object_key':prefix+'.bin','object_version':'owned-v1','commit_key':prefix+'.commit.json','commit_version':'owned-v2'};calls=[];closes=[];abort_calls=[];pipe_inodes=[];events=[];deadlines=[]
pipe_allocations=[]
real_pipe=os.pipe
def pipe_spy(*args,**kwargs):
 pipe_allocations.append(1)
 return real_pipe(*args,**kwargs)
os.pipe=pipe_spy
if hasattr(os,'pipe2'):
 real_pipe2=os.pipe2
 def pipe2_spy(*args,**kwargs):
  pipe_allocations.append(1)
  return real_pipe2(*args,**kwargs)
 os.pipe2=pipe2_spy
def callback(c,r,rc,fd,event,deadline):
 calls.append(fd);pipe_inodes.append(os.fstat(fd).st_ino);events.append(event);deadlines.append(deadline)
 if case in ('replay-close-fault','replay-success','replay-final-false','replay-journal-true'):
  stage=True;journal=(len(calls)>1 or case=='replay-journal-true') and case!='replay-final-false'
  if len(calls)>1:assert os.read(fd,1)==b''
 else:
  stage=journal=False;body=b''
  while True:
   ready,_,_=select.select([fd],[],[],1)
   assert ready
   chunk=os.read(fd,65536)
   if not chunk:break
   body+=chunk
  assert body==data
 if case=='callback-metadata-mutation':c['keyId']='other-key'
 if case=='callback-cancel':event.set()
 if case=='callback-late':mod.time.monotonic=lambda:deadline
 result={'schema':'sg.local-cipher-import.v1','state':'cipher-journal-bound','context':dict(c),'job_id':r['job_id'],'request_digest':r['request_digest'],'artifact':dict(r['artifact']),'replay_stage':stage,'replay_journal':journal}
 if case=='wrong-result-schema':result['schema']='invented'
 if case=='wrong-result-flags':result['replay_stage']=1
 return result
if case=='replay-close-fault':
 realclose=mod._close_fd_no_retry_local
 def closefault(fd):
  closes.append(fd)
  if len(closes)==1:return False
  return realclose(fd)
 mod._close_fd_no_retry_local=closefault
if case=='postfinish-abort-fault':
 realabort=mod.ImportBodyBridge.abort
 def abortfault(self):
  abort_calls.append(1)
  if self.worker_quiescent:raise RuntimeError('owned abort fault')
  return realabort(self)
 mod.ImportBodyBridge.abort=abortfault
options={} if case=='default-registry' else {'import_request_registry':ImportRequestRegistry()}
if case.startswith('managed-'):
 from lib.runtime_managed_http import create_managed_server
 server=create_managed_server(lambda x:{},lambda x:{},lambda:True,'m'*40,'b'*40,'s'*40,operation_context=ctx,upstream_port=65533,import_cb=callback,**options)
else:server=mod.create_management_server(lambda x:{},lambda x:{},'m'*40,'b'*40,'s'*40,operation_context=ctx,import_cb=None if case=='disabled' else callback,**options)
end_calls=[];unregister_calls=[]
if case=='gate-end-fault':
 def end_fault():
  end_calls.append(1)
  raise RuntimeError('owned gate-end fault')
 server.gate.end_mutation=end_fault
if case=='unregister-fault':
 def unregister_fault(handle):
  unregister_calls.append(handle)
  raise RuntimeError('owned unregister fault')
 server.import_request_registry.unregister=unregister_fault
if case=='registry-closed':server.import_request_registry.close_and_cancel()
if case=='registry-full':
 for unused in range(32):server.import_request_registry.register()
thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02});thread.start();wire=b''
try:
 meta=json.dumps({'context':ctx,'record':rec,'remote_receipt':receipt},separators=(',',':'));frame=('POST /_management/import HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer '+'m'*40+'\r\nContent-Type: application/vnd.sg.cipher-export+v1\r\nContent-Length: '+str(len(data))+'\r\nX-SG-Import-Metadata: '+meta+'\r\nConnection: close\r\n\r\n').encode()+data
 if case in ('unauthorized','backend-role','get-backend','managed-get-backend'):
  frame=frame.replace(('Bearer '+'m'*40).encode(),('Bearer '+'b'*40).encode())
 if case in ('get-management','get-backend','managed-get-backend','managed-get-management'):
  frame=frame.replace(b'POST ',b'GET ',1)
 if case in ('unauthorized','backend-role','get-backend','get-management','managed-get-backend','managed-get-management','disabled'):
  frame=frame.split(b'\r\n\r\n',1)[0]+b'\r\n\r\n'
 if case=='bad-content-type':frame=frame.replace(b'application/vnd.sg.cipher-export+v1',b'application/json')
 if case=='duplicate-length':frame=frame.replace(b'Content-Length: ',b'Content-Length: 17\r\nContent-Length: ',1)
 if case=='transfer-encoding':frame=frame.replace(b'Connection: close',b'Transfer-Encoding: chunked\r\nConnection: close')
 if case=='wrong-body-sha':frame=frame[:-len(data)]+b'X'*len(data)
 if case=='prequeued-trailer':frame+=b'Z'
 with socket.create_connection(server.server_address,timeout=2) as client:
  client.settimeout(3);client.sendall(frame)
  while True:
   try:part=client.recv(8192)
   except ConnectionResetError:break
   if not part:break
   wire+=part
finally:
 server.shutdown();thread.join(2);assert not thread.is_alive();server.server_close()
status=int(wire.split(b' ',2)[1]) if wire else 0;registry=server.import_request_registry
complete=False;ack=None
if status==200:
 head,body=wire.split(b'\r\n\r\n',1)
 headers=dict(line.split(b': ',1) for line in head.split(b'\r\n')[1:])
 assert len(body)==int(headers[b'Content-Length'])
 ack=json.loads(body)
 assert set(ack)=={'schema','state','context','job_id','request_digest','artifact','replay_stage','replay_journal'}
 assert ack['schema']=='sg.local-cipher-import.v1' and ack['state']=='cipher-journal-bound'
 assert ack['context']==ctx and ack['job_id']==job and ack['request_digest']==req and ack['artifact']==art
 assert type(ack['replay_stage'])is bool and type(ack['replay_journal'])is bool
 complete=True
if case in ('replay-success','replay-journal-true'):
 assert len(calls)==2 and events[0] is events[1] and deadlines[0]==deadlines[1] and len(pipe_allocations)==2
 assert ack['replay_stage'] is True and ack['replay_journal'] is (case=='replay-journal-true')

print(json.dumps({'case':case,'status':status,'callback_count':len(calls),'gate_mutating':server.gate._mutating,'registry_count':None if registry is None else registry.active_count(),'complete_frame':complete,'abort_calls':len(abort_calls),'end_calls':len(end_calls),'unregister_calls':len(unregister_calls),'close_calls':len(closes),'close_retry':len(closes)>1 and closes[0]==closes[1]}))
'''
CONTROL_CHILD=r'''import sys,socket,json,hashlib,email.message
sys.path.insert(0,sys.argv[1]);import lib.runtime_management_http as mod
from lib.runtime_operation_identity import checkpoint_digest
ctx={'instanceId':'inst-1','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'key-1'};job='b'*32;req=checkpoint_digest(ctx,job);art={'leaf':'sg-encrypted-'+job+'.bin','bytes':1,'sha256':hashlib.sha256(b'x').hexdigest()};rec={'schema':'sg.local-job.v1','state':'artifact-verified','job_id':job,'request_digest':req,'artifact':dict(art)};prefix=f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/{job}/{req}/{art['sha256']}";receipt={'schema':'sg.remote-checkpoint.v1','state':'remote-committed','context':dict(ctx),'job_id':job,'request_digest':req,'artifact':dict(art),'object_key':prefix+'.bin','object_version':'v1','commit_key':prefix+'.commit.json','commit_version':'v2'};case=sys.argv[2];original=KeyboardInterrupt('original-owned');secondary=SystemExit('secondary-owned');status=[]
class Bridge:
 @property
 def worker_quiescent(self):return case!='finished-unknown-worker'
 def __init__(self,*args):pass
 def start(self):return 0
 def finish(self,**kwargs):
  if case=='finished-unknown-worker':return {'state':'body-verified'}
  raise original
 def abort(self):
  if case=='finish-controlflow-mask':raise secondary
mod.ImportBodyBridge=Bridge
def callback(c,r,rc,fd,event,deadline):
 if case=='ordinary-callback-raw':raise ValueError('OWNED-RAW-FAULT')
 return {'schema':'sg.local-cipher-import.v1','state':'cipher-journal-bound','context':dict(c),'job_id':r['job_id'],'request_digest':r['request_digest'],'artifact':dict(r['artifact']),'replay_stage':False,'replay_journal':False}
server=mod.create_management_server(lambda x:{},lambda x:{},'m'*40,'b'*40,'s'*40,operation_context=ctx,import_cb=callback);handler=object.__new__(mod._ManagementHandler);handler.server=server;handler.headers=email.message.Message();handler.headers['Content-Type']='application/vnd.sg.cipher-export+v1';handler.headers['Content-Length']='1';handler.headers['X-SG-Import-Metadata']=json.dumps({'context':ctx,'record':rec,'remote_receipt':receipt});handler.connection,peer=socket.socketpair();handler._send_response_raw=lambda code,*args:status.append(code);caught=None
try:
 try:handler._handle_import()
 except BaseException as error:caught=error
 result={'case':case,'caught_class':None if caught is None else type(caught).__name__,'original_preserved':caught is original,'raw_fault_propagated':type(caught)is ValueError,'statuses':status,'gate_mutating':server.gate._mutating,'registry_count':server.import_request_registry.active_count()}
finally:handler.connection.close();peer.close();server.server_close()
print(json.dumps(result))
'''
FD_CHILD=r'''import sys,json,hashlib,socket,threading,select,os
sys.path.insert(0,sys.argv[1]);import lib.runtime_management_http as mod
from lib.runtime_operation_identity import checkpoint_digest
from lib.runtime_import_request_registry import ImportRequestRegistry
case=sys.argv[2];data=b'OWNED-HTTP-CIPHER';ctx={'instanceId':'inst-1','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'key-1'};job='b'*32;req=checkpoint_digest(ctx,job);art={'leaf':'sg-encrypted-'+job+'.bin','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()};rec={'schema':'sg.local-job.v1','job_id':job,'request_digest':req,'state':'artifact-verified','artifact':dict(art)};prefix=f"cp/v1/{ctx['instanceId']}/{ctx['imageDigest']}/{job}/{req}/{art['sha256']}";receipt={'schema':'sg.remote-checkpoint.v1','state':'remote-committed','context':dict(ctx),'job_id':job,'request_digest':req,'artifact':dict(art),'object_key':prefix+'.bin','object_version':'owned-v1','commit_key':prefix+'.commit.json','commit_version':'owned-v2'};calls=[];closes=[];abort_calls=[];pipe_inodes=[];events=[];deadlines=[]
pipe_allocations=[]
real_pipe=os.pipe
def pipe_spy(*args,**kwargs):
 pipe_allocations.append(1)
 return real_pipe(*args,**kwargs)
os.pipe=pipe_spy
if hasattr(os,'pipe2'):
 real_pipe2=os.pipe2
 def pipe2_spy(*args,**kwargs):
  pipe_allocations.append(1)
  return real_pipe2(*args,**kwargs)
 os.pipe2=pipe2_spy
def callback(c,r,rc,fd,event,deadline):
 calls.append(fd);pipe_inodes.append(os.fstat(fd).st_ino);events.append(event);deadlines.append(deadline)
 if case in ('replay-close-fault','replay-success','replay-final-false','replay-journal-true','replay-fcntl-replacement'):
  stage=True;journal=(len(calls)>1 or case=='replay-journal-true') and case!='replay-final-false'
  if len(calls)>1:assert os.read(fd,1)==b''
 else:
  stage=journal=False;body=b''
  while True:
   ready,_,_=select.select([fd],[],[],1)
   assert ready
   chunk=os.read(fd,65536)
   if not chunk:break
   body+=chunk
  assert body==data
 if case=='callback-metadata-mutation':c['keyId']='other-key'
 if case=='callback-cancel':event.set()
 if case=='callback-late':mod.time.monotonic=lambda:deadline
 result={'schema':'sg.local-cipher-import.v1','state':'cipher-journal-bound','context':dict(c),'job_id':r['job_id'],'request_digest':r['request_digest'],'artifact':dict(r['artifact']),'replay_stage':stage,'replay_journal':journal}
 if case=='wrong-result-schema':result['schema']='invented'
 if case=='wrong-result-flags':result['replay_stage']=1
 return result
if case=='replay-close-fault':
 realclose=mod._close_fd_no_retry_local
 def closefault(fd):
  closes.append(fd)
  if len(closes)==1:return False
  return realclose(fd)
 mod._close_fd_no_retry_local=closefault
if case=='postfinish-abort-fault':
 realabort=mod.ImportBodyBridge.abort
 def abortfault(self):
  abort_calls.append(1)
  if self.worker_quiescent:raise RuntimeError('owned abort fault')
  return realabort(self)
 mod.ImportBodyBridge.abort=abortfault
import tempfile,fcntl
replacement_fd=None;replacement_path=None;before_flags=None;first_reader=None;stat_calls=[]
if case=='replay-fcntl-replacement':
 if hasattr(os,'pipe2'):delattr(os,'pipe2')
 realstat=mod._safe_fstat_local
 def swapped_stat(fd):
  global replacement_fd,replacement_path,before_flags,first_reader
  result=realstat(fd);stat_calls.append(fd)
  if len(stat_calls)==1:first_reader=fd
  if len(stat_calls)==2:
   tempfd,replacement_path=tempfile.mkstemp(prefix='owned-replay-fd-')
   os.close(tempfd);os.close(first_reader)
   replacement_fd=os.open(replacement_path,os.O_RDONLY|os.O_CLOEXEC)
   assert replacement_fd==first_reader
   before_flags=fcntl.fcntl(replacement_fd,fcntl.F_GETFL)
  return result
 mod._safe_fstat_local=swapped_stat

options={} if case=='default-registry' else {'import_request_registry':ImportRequestRegistry()}
if case.startswith('managed-'):
 from lib.runtime_managed_http import create_managed_server
 server=create_managed_server(lambda x:{},lambda x:{},lambda:True,'m'*40,'b'*40,'s'*40,operation_context=ctx,upstream_port=65533,import_cb=callback,**options)
else:server=mod.create_management_server(lambda x:{},lambda x:{},'m'*40,'b'*40,'s'*40,operation_context=ctx,import_cb=None if case=='disabled' else callback,**options)
end_calls=[];unregister_calls=[]
if case=='gate-end-fault':
 def end_fault():
  end_calls.append(1)
  raise RuntimeError('owned gate-end fault')
 server.gate.end_mutation=end_fault
if case=='unregister-fault':
 def unregister_fault(handle):
  unregister_calls.append(handle)
  raise RuntimeError('owned unregister fault')
 server.import_request_registry.unregister=unregister_fault
if case=='registry-closed':server.import_request_registry.close_and_cancel()
if case=='registry-full':
 for unused in range(32):server.import_request_registry.register()
thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02});thread.start();wire=b''
try:
 meta=json.dumps({'context':ctx,'record':rec,'remote_receipt':receipt},separators=(',',':'));frame=('POST /_management/import HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer '+'m'*40+'\r\nContent-Type: application/vnd.sg.cipher-export+v1\r\nContent-Length: '+str(len(data))+'\r\nX-SG-Import-Metadata: '+meta+'\r\nConnection: close\r\n\r\n').encode()+data
 if case in ('unauthorized','backend-role','get-backend','managed-get-backend'):
  frame=frame.replace(('Bearer '+'m'*40).encode(),('Bearer '+'b'*40).encode())
 if case in ('get-management','get-backend','managed-get-backend','managed-get-management'):
  frame=frame.replace(b'POST ',b'GET ',1)
 if case in ('unauthorized','backend-role','get-backend','get-management','managed-get-backend','managed-get-management','disabled'):
  frame=frame.split(b'\r\n\r\n',1)[0]+b'\r\n\r\n'
 if case=='bad-content-type':frame=frame.replace(b'application/vnd.sg.cipher-export+v1',b'application/json')
 if case=='duplicate-length':frame=frame.replace(b'Content-Length: ',b'Content-Length: 17\r\nContent-Length: ',1)
 if case=='transfer-encoding':frame=frame.replace(b'Connection: close',b'Transfer-Encoding: chunked\r\nConnection: close')
 if case=='wrong-body-sha':frame=frame[:-len(data)]+b'X'*len(data)
 if case=='prequeued-trailer':frame+=b'Z'
 with socket.create_connection(server.server_address,timeout=2) as client:
  client.settimeout(3);client.sendall(frame)
  while True:
   try:part=client.recv(8192)
   except ConnectionResetError:break
   if not part:break
   wire+=part
finally:
 server.shutdown();thread.join(2);assert not thread.is_alive();server.server_close()
status=int(wire.split(b' ',2)[1]) if wire else 0;registry=server.import_request_registry
complete=False;ack=None
if status==200:
 head,body=wire.split(b'\r\n\r\n',1)
 headers=dict(line.split(b': ',1) for line in head.split(b'\r\n')[1:])
 assert len(body)==int(headers[b'Content-Length'])
 ack=json.loads(body)
 assert set(ack)=={'schema','state','context','job_id','request_digest','artifact','replay_stage','replay_journal'}
 assert ack['schema']=='sg.local-cipher-import.v1' and ack['state']=='cipher-journal-bound'
 assert ack['context']==ctx and ack['job_id']==job and ack['request_digest']==req and ack['artifact']==art
 assert type(ack['replay_stage'])is bool and type(ack['replay_journal'])is bool
 complete=True
if case in ('replay-success','replay-journal-true'):
 assert len(calls)==2 and events[0] is events[1] and deadlines[0]==deadlines[1] and len(pipe_allocations)==2
 assert ack['replay_stage'] is True and ack['replay_journal'] is (case=='replay-journal-true')

after_flags=fcntl.fcntl(replacement_fd,fcntl.F_GETFL)
os.close(replacement_fd);os.unlink(replacement_path)
print(json.dumps({'replacement_flags_unchanged':before_flags==after_flags,'case':case,'status':status,'callback_count':len(calls),'gate_mutating':server.gate._mutating,'registry_count':None if registry is None else registry.active_count(),'complete_frame':complete,'abort_calls':len(abort_calls),'end_calls':len(end_calls),'unregister_calls':len(unregister_calls),'close_calls':len(closes),'close_retry':len(closes)>1 and closes[0]==closes[1]}))
'''
@pytest.mark.parametrize("case,status,gate,count",[('positive-explicit-registry', 200, False, 0), ('default-registry', 200, False, 0), ('replay-close-fault', 503, True, 1), ('postfinish-abort-fault', 200, False, 0), ('replay-success', 200, False, 0), ('replay-final-false', 503, False, 0), ('managed-cold', 200, False, 0), ('unauthorized', 401, False, 0), ('backend-role', 401, False, 0), ('get-management', 405, False, 0), ('get-backend', 401, False, 0), ('managed-get-management', 405, False, 0), ('managed-get-backend', 401, False, 0), ('disabled', 503, False, 0), ('bad-content-type', 400, False, 0), ('duplicate-length', 400, False, 0), ('transfer-encoding', 400, False, 0), ('wrong-body-sha', 503, False, 0), ('prequeued-trailer', 503, False, 0), ('replay-journal-true', 200, False, 0), ('callback-metadata-mutation', 503, False, 0), ('callback-cancel', 503, False, 0), ('callback-late', 503, False, 0), ('wrong-result-schema', 503, False, 0), ('wrong-result-flags', 503, False, 0), ('gate-end-fault', 503, True, 0), ('unregister-fault', 503, True, 1), ('registry-closed', 503, False, 0), ('registry-full', 503, False, 32)])
def test_owned_http(case,status,gate,count):
    out=_run(HTTP_CHILD,case)
    assert out["status"]==status
    assert out["gate_mutating"] is gate
    assert out["registry_count"]==count
    assert out["close_retry"] is False
    assert out["complete_frame"] is (status==200)
    if case=="postfinish-abort-fault":assert out["abort_calls"]==0
@pytest.mark.parametrize("case",['finish-controlflow-mask','ordinary-callback-raw','finished-unknown-worker'])
def test_owned_controlflow(case):
    out=_run(CONTROL_CHILD,case)
    if case=='finish-controlflow-mask':
        assert out['caught_class']=='KeyboardInterrupt' and out['original_preserved'] is True
        assert out['gate_mutating'] is True and out['registry_count']==1
    elif case=='finished-unknown-worker':
        assert out['caught_class'] is None and out['statuses']==[503]
        assert out['gate_mutating'] is True and out['registry_count']==1
    else:
        assert out['caught_class'] is None and out['raw_fault_propagated'] is False
        assert out['statuses']==[503] and out['gate_mutating'] is False and out['registry_count']==0

@pytest.mark.parametrize("case,key",[('gate-end-fault','end_calls'),('unregister-fault','unregister_calls')])
def test_failed_ownership_release_not_retried(case,key):
    out=_run(HTTP_CHILD,case)
    assert out['status']==503 and out[key]==1 and out['gate_mutating'] is True

def test_replay_replaced_descriptor_not_mutated():
    out=_run(FD_CHILD,'replay-fcntl-replacement')
    assert out['replacement_flags_unchanged'] is True
    assert out['status']==503 and out['callback_count']==1
    assert out['gate_mutating'] is True and out['registry_count']==1
    assert out['complete_frame'] is False
