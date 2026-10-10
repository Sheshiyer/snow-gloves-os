import unittest,pathlib,importlib.util,json,threading,http.client,time,select
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from lib.runtime_operation_identity import checkpoint_digest
from lib import runtime_managed_http as m
class Review(unittest.TestCase):
 def setUp(self):
  self.calls=[];calls=self.calls
  class Upstream(BaseHTTPRequestHandler):
   protocol_version="HTTP/1.1"
   def handle(self):
    try:super().handle()
    except (ConnectionResetError,BrokenPipeError):pass
   def log_message(self,*args):pass
   def do_GET(self):calls.append(self.path);self.send_response(200);self.send_header('Content-Type',self.server.content_type);self.send_header('Content-Length','11');self.end_headers();self.wfile.write(b'{"data":[]}')
   def do_POST(self):
    calls.append(self.rfile.read(int(self.headers['Content-Length'])))
    if self.server.mode=='oversized-header':
     try:self.connection.sendall(b'HTTP/1.1 200 OK\r\nX-Fixture: '+b'x'*33000+b'\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}')
     except OSError:pass
     self.close_connection=True;return
    if self.server.mode=='slow-header':
     try:
      self.connection.sendall(b'HTTP/1.1 200 OK\r\n')
      for _ in range(10):self.connection.sendall(b'X-Fixture: owned\r\n');time.sleep(0.08)
     except OSError:pass
     return
    if self.server.mode=='trickle-json':
     self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length','10');self.end_headers()
     try:
      for _ in range(10):self.wfile.write(b'x');self.wfile.flush();time.sleep(0.08)
     except OSError:pass
     return
    if self.server.mode=='json':
     self.send_response(200);self.send_header('Content-Type',self.server.content_type);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}');return
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Transfer-Encoding','chunked');self.end_headers()
    def chunk(value):self.wfile.write(('%x\r\n'%len(value)).encode()+value+b'\r\n');self.wfile.flush()
    try:
     chunk(b'data: first\n\n');self.server.stream_started.set()
     if self.server.mode=='broken-chunk':
      self.wfile.write(b'not-a-chunk-size\r\n');self.wfile.flush();self.close_connection=True;return
     if self.server.mode=='flood':
      for _ in range(4096):chunk(b'data: '+b'x'*16370+b'\n\n')
     while not self.server.release.wait(0.02):
      ready,_,_=select.select([self.connection],[],[],0)
      if ready and not self.connection.recv(1):self.server.disconnected.set();return
     chunk(b'data: [DONE]\n\n');self.wfile.write(b'0\r\n\r\n');self.wfile.flush()
    except OSError:self.server.disconnected.set()

  self.up=ThreadingHTTPServer(('127.0.0.1',0),Upstream);self.up.content_type='application/json';self.up.mode='json';self.up.release=threading.Event();self.up.stream_started=threading.Event();self.up.disconnected=threading.Event();self.ut=threading.Thread(target=self.up.serve_forever,daemon=True);self.ut.start();self.ctx={'instanceId':'heyzack','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'fixture-key'};self.healthy=True;self.admitted=True
  self.server=m.create_managed_server(lambda x:{'state':'fixture'},lambda x:{'state':'fixture'},lambda:self.healthy,'m'*40,'b'*40,'s'*40,operation_context=self.ctx,upstream_port=self.up.server_address[1],admission_probe=lambda:self.admitted);self.t=threading.Thread(target=self.server.serve_forever,daemon=True);self.t.start()
 def tearDown(self):self.up.release.set();self.server.shutdown();self.server.server_close();self.t.join(2);self.up.shutdown();self.up.server_close();self.ut.join(2)
 def request(self,path,method='GET',body=None,key='b'*40):
  conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=2);raw=json.dumps(body).encode() if body is not None else None;conn.request(method,path,raw,{'Authorization':'Bearer '+key,'Content-Type':'application/json'});r=conn.getresponse();status=r.status;value=r.read();conn.close();return status,value
 def assert_gate_released(self):
  deadline=time.monotonic()+2
  while True:
   try:self.server.gate.begin_mutation();break
   except RuntimeError:
    if time.monotonic()>=deadline:raise
    time.sleep(0.01)
  self.server.gate.end_mutation()
 def test_backend_role_denied(self):self.assertEqual(self.request('/v1/models',key='m'*40)[0],401);self.assertEqual(self.calls,[])
 def test_valid_chat(self):self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'owned','messages':[{'role':'user','content':'fixture'}]})[0],200)
 def test_valid_repeated_message_keys(self):self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'owned','messages':[{'role':'system','content':'fixture'},{'role':'user','content':'fixture'}]})[0],200)
 def test_get_body_denied_before_upstream(self):self.assertEqual(self.request('/v1/models',body={})[0],400);self.assertEqual(self.calls,[])
 def test_unhealthy_readiness_returns_503(self):self.healthy=False;self.assertEqual(self.request('/_management/ready',key='m'*40)[0],503)
 def open_stream(self):
  self.up.mode='stream';conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=3);conn.request('POST','/v1/chat/completions',json.dumps({'model':'fixture','stream':True}),{'Authorization':'Bearer '+'b'*40,'Content-Type':'application/json'});response=conn.getresponse();self.assertEqual(response.status,200);return conn,response
 def test_chunked_sse_completion(self):
  conn,response=self.open_stream();self.up.release.set();self.assertEqual(response.read(),b'data: first\n\ndata: [DONE]\n\n');conn.close()
 def test_quiet_sse_survives_one_second(self):
  conn,response=self.open_stream();self.assertEqual(response.read(13),b'data: first\n\n');time.sleep(1.3);self.up.release.set();self.assertEqual(response.read(),b'data: [DONE]\n\n');conn.close()
 def test_stream_blocks_mutation_until_cancel(self):
  conn,response=self.open_stream();self.assertEqual(response.read(13),b'data: first\n\n');payload={'job_id':'b'*32,'request_digest':checkpoint_digest(self.ctx,'b'*32)};self.assertEqual(self.request('/_management/checkpoint','POST',payload,key='m'*40)[0],409)
  response.close();conn.close();self.assertTrue(self.up.disconnected.wait(2),'upstream connection not cancelled')
  deadline=time.monotonic()+2
  while time.monotonic()<deadline:
   status,_=self.request('/_management/checkpoint','POST',payload,key='m'*40)
   if status==200:break
   time.sleep(0.05)
  self.assertEqual(status,200)
  self.assertFalse(any(t.is_alive() and '_reader_thread' in t.name for t in threading.enumerate()))
 def test_backpressure_cancel_releases_reader_and_gate(self):
  self.up.mode='flood';conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=3);conn.request('POST','/v1/chat/completions',json.dumps({'model':'fixture','stream':True}),{'Authorization':'Bearer '+'b'*40,'Content-Type':'application/json'});response=conn.getresponse();self.assertEqual(response.status,200);time.sleep(0.3);response.close();conn.close()
  self.assertTrue(self.up.disconnected.wait(3));deadline=time.monotonic()+3
  while any(t.is_alive() and '_reader_thread' in t.name for t in threading.enumerate()) and time.monotonic()<deadline:time.sleep(0.05)
  self.assertFalse(any(t.is_alive() and '_reader_thread' in t.name for t in threading.enumerate()));self.assert_gate_released()
 def test_noncanonical_content_type_denied(self):
  self.up.content_type='application/json-foreign';self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'fixture'})[0],503)
 def test_slow_upstream_headers_absolute_deadline(self):
  self.up.mode='slow-header';self.server.upstream_timeout=0.2;start=time.monotonic();status,_=self.request('/v1/chat/completions','POST',{'model':'fixture'});self.assertEqual(status,503);self.assertLess(time.monotonic()-start,0.6)
  self.assert_gate_released()
 def test_trickle_json_absolute_deadline(self):
  self.up.mode='trickle-json';self.server.upstream_timeout=0.2;start=time.monotonic();status,_=self.request('/v1/chat/completions','POST',{'model':'fixture'});self.assertEqual(status,503);self.assertLess(time.monotonic()-start,0.6)
  self.assert_gate_released()
 def test_upstream_header_aggregate_limit(self):
  self.up.mode='oversized-header';self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'fixture'})[0],503)
  self.assert_gate_released()
 def test_healthy_but_unadmitted_chat_denied_before_upstream(self):
  self.admitted=False;self.assertEqual(self.request('/healthz')[0],200)
  self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'fixture'})[0],503);self.assertEqual(self.calls,[])
 def test_nonboolean_admission_denied(self):
  self.admitted=1;self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'fixture'})[0],503);self.assertEqual(self.calls,[])
 def test_admission_exception_denies_before_upstream(self):
  def unavailable():raise RuntimeError('owned fixture')
  self.server.admission_probe=unavailable
  self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'fixture'})[0],503);self.assertEqual(self.calls,[])
 def test_admission_revoked_before_forward_denies_upstream(self):
  decisions=iter([True,False]);self.server.admission_probe=lambda:next(decisions)
  self.assertEqual(self.request('/v1/chat/completions','POST',{'model':'fixture'})[0],503);self.assertEqual(self.calls,[]);self.assert_gate_released()
 def test_stream_error_after_headers_closes_without_second_response(self):
  self.up.mode='broken-chunk';conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=3);conn.request('POST','/v1/chat/completions',json.dumps({'model':'fixture','stream':True}),{'Authorization':'Bearer '+'b'*40,'Content-Type':'application/json'});response=conn.getresponse();self.assertEqual(response.status,200);raw=response.read();self.assertEqual(raw,b'data: first\n\n');self.assertNotIn(b'HTTP/',raw);conn.close();self.assert_gate_released()
 def test_absent_admission_defaults_held(self):
  other=m.create_managed_server(lambda x:{},lambda x:{},lambda:True,'m'*40,'b'*40,'s'*40,operation_context=self.ctx,upstream_port=self.up.server_address[1])
  try:self.assertIs(other.admission_probe(),False)
  finally:other.server_close()
if __name__=='__main__':unittest.main(verbosity=2)
