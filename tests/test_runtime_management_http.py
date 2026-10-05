from lib.runtime_operation_identity import checkpoint_digest, restore_digest
import unittest,threading,http.client,json,socket,time
from lib.runtime_management_http import create_management_server,OperationGate
class Review(unittest.TestCase):
 def setUp(self):
  self.calls=[];self.key='m'*40;self.context={'instanceId':'heyzack','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'fixture-key'};self.payload={'job_id':'a'*32,'request_digest':checkpoint_digest(self.context,'a'*32)}
  def callback(value):self.calls.append(value);return {'state':'local-only'}
  self.server=create_management_server(callback,callback,self.key,'b'*40,'s'*40,connection_timeout=0.2,operation_context=self.context);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.port=self.server.server_address[1]
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(2)
 def request(self,body=None,key=None,path='/_management/checkpoint',method='POST',headers=None):
  raw=json.dumps(self.payload if body is None else body).encode();c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=2);h={'Authorization':'Bearer '+(self.key if key is None else key),'Content-Type':'application/json'};h.update(headers or {});c.request(method,path,raw,h);r=c.getresponse();value=(r.status,r.read());c.close();return value
 def test_valid_checkpoint(self):
  status,body=self.request();self.assertEqual(status,200);self.assertEqual(self.calls,[self.payload])
 def test_wrong_roles_never_mutate(self):
  for key in ['b'*40,'s'*40,'x'*40]:self.assertEqual(self.request(key=key)[0],401)
  self.assertEqual(self.calls,[])
 def test_unknown_fields_denied(self):
  self.assertEqual(self.request(body={**self.payload,'upstream':'evil'})[0],400);self.assertEqual(self.calls,[])
 def test_invalid_job_newline_denied(self):
  self.assertEqual(self.request(body={**self.payload,'job_id':'a'*32+'\n'})[0],400)
 def test_ambiguous_paths_denied(self):
  for p in ['/_management/checkpoint?q=1','//_management/checkpoint','/_management/%63heckpoint']:self.assertEqual(self.request(path=p)[0],400)
  self.assertEqual(self.calls,[])
 def test_active_stream_holds_then_releases(self):
  token=self.server.gate.begin_stream();self.assertEqual(self.request()[0],409);self.assertEqual(self.calls,[]);self.server.gate.end_stream(token);self.assertEqual(self.request()[0],200)
 def test_mutating_blocks_stream_and_other_mutation(self):
  self.server.gate.begin_mutation()
  with self.assertRaises(RuntimeError):self.server.gate.begin_stream()
  self.assertEqual(self.request()[0],409);self.server.gate.end_mutation();self.assertEqual(self.request()[0],200)
 def test_restore_requires_exact_artifact_fields(self):
  self.assertEqual(self.request(path='/_management/restore')[0],400)
  art={'leaf':'sg-encrypted-'+'c'*32+'.bin','bytes':32,'sha256':'d'*64};value={'restore_job_id':'d'*32,'source_checkpoint_job_id':'c'*32,'source_request_digest':'e'*64,**art};value['request_digest']=restore_digest(self.context,'d'*32,'c'*32,'e'*64,art);self.assertEqual(self.request(body=value,path='/_management/restore')[0],200)
 def test_body_length_over_limit_never_mutates(self):
  self.assertEqual(self.request(headers={'Content-Length':'2049'})[0],400);self.assertEqual(self.calls,[])
 def raw(self,request):
  with socket.create_connection(('127.0.0.1',self.port),timeout=2) as s:s.sendall(request);return s.recv(4096)
 def test_duplicate_auth_denied(self):
  r=self.raw(('POST /_management/checkpoint HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+self.key+'\r\nAuthorization: Bearer '+self.key+'\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n{}').encode());self.assertIn(b'401',r);self.assertEqual(self.calls,[])
 def test_stalled_body_never_mutates(self):
  r=self.raw(('POST /_management/checkpoint HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+self.key+'\r\nContent-Length: 10\r\nContent-Type: application/json\r\n\r\n{').encode());self.assertNotIn(b'200',r);self.assertEqual(self.calls,[])
 def test_unknown_method_authenticated(self):
  self.assertEqual(self.request(key='x'*40,method='WUT')[0],401);self.assertEqual(self.request(method='WUT')[0],405)
 def test_callback_failure_releases_gate(self):
  def failed(value):raise RuntimeError('fixture-sensitive-error')
  self.server.checkpoint_cb=failed;status,body=self.request();self.assertEqual(status,503);self.assertNotIn(b'fixture-sensitive-error',body);token=self.server.gate.begin_stream();self.server.gate.end_stream(token)
 def test_noncanonical_length_denied(self):
  raw=json.dumps(self.payload).encode();self.assertEqual(self.request(headers={'Content-Length':'0'+str(len(raw))})[0],400);self.assertEqual(self.calls,[])
 def test_duplicate_body_keys_denied(self):
  raw=('POST /_management/checkpoint HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+self.key+'\r\nContent-Length: 21\r\nContent-Type: application/json\r\n\r\n{"job_id":1,"job_id":2}').encode();r=self.raw(raw);self.assertNotIn(b'200',r);self.assertEqual(self.calls,[])
 def test_nonfinite_payload_denied(self):
  self.assertEqual(self.request(body={**self.payload,'bytes':float('nan')})[0],400);self.assertEqual(self.calls,[])
 def test_gate_rejects_duplicate_release(self):
  token=self.server.gate.begin_stream();self.server.gate.end_stream(token)
  with self.assertRaises(RuntimeError):self.server.gate.end_stream(token)
 def test_slow_header_absolute_deadline(self):
  c=socket.create_connection(('127.0.0.1',self.port),timeout=2);done=threading.Event()
  def drip():
   try:
    c.sendall(b'POST /_management/checkpoint HTTP/1.1\r\n')
    for i in range(12):c.sendall(b'X: value\r\n');time.sleep(0.08)
   except OSError:pass
   finally:done.set()
  t=threading.Thread(target=drip,daemon=True);t.start();start=time.monotonic()
  try:
   c.recv(4096);elapsed=time.monotonic()-start;self.assertLess(elapsed,0.5);self.assertEqual(self.calls,[])
  finally:c.close();t.join(2)
 def test_requestline_and_headers_share_total_limit(self):
  raw=('POST /'+('x'*19000)+' HTTP/1.1\r\nHost: fixture\r\nX: '+('y'*15000)+'\r\nAuthorization: Bearer '+self.key+'\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n{}').encode();r=self.raw(raw);self.assertIn(b'431',r);self.assertEqual(self.calls,[])
 def test_connection_capacity_recovers(self):
  self.server.conn_timeout=2.0
  held=[]
  try:
   for _ in range(8):
    c=socket.create_connection(('127.0.0.1',self.port),timeout=2);c.sendall(b'POST ');held.append(c)
   deadline=time.monotonic()+1
   while self.server.conn_semaphore._value and time.monotonic()<deadline:time.sleep(0.01)
   self.assertEqual(self.server.conn_semaphore._value,0)
   extra=socket.create_connection(('127.0.0.1',self.port),timeout=2)
   try:extra.sendall(b'GET / HTTP/1.1\r\n\r\n');self.assertEqual(extra.recv(4096),b'')
   except ConnectionResetError:pass
   finally:extra.close()
  finally:
   for c in held:c.close()
  time.sleep(0.3);self.assertEqual(self.request()[0],200)
 def test_oversized_requestline_generic_denial(self):
  r=self.raw(b'POST /'+b'fixture-secret-'*2600+b' HTTP/1.1\r\n\r\n');self.assertIn(b'431',r);self.assertNotIn(b'fixture-secret',r);self.assertEqual(self.calls,[])
 def test_changed_digest_rejected_before_callback(self):
  self.assertEqual(self.request(body={**self.payload,'request_digest':'0'*64})[0],400);self.assertEqual(self.calls,[])
 def test_context_copy_isolated_from_callers(self):
  self.context['instanceId']='other-company';self.assertEqual(self.request()[0],200)
 def test_checkpoint_payload_cannot_replay_as_restore(self):
  self.assertEqual(self.request(path='/_management/restore')[0],400);self.assertEqual(self.calls,[])
if __name__=='__main__':unittest.main(verbosity=2)
