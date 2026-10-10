"""Actual loopback HTTP readiness authentication, framing and capacity checks."""
import unittest,threading,http.client,socket,time
from scripts.lib import runtime_readiness_http as m

MANAGEMENT='m'*40;BACKEND='b'*40;STORAGE='s'*40
class Review(unittest.TestCase):
 def setUp(self):
  self.calls=0
  def probe():self.calls+=1;return True
  self.server=m.create_readiness_server(probe,MANAGEMENT,BACKEND,STORAGE,connection_timeout=0.3);self.port=self.server.server_port
  self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=0.01),daemon=True);self.thread.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=1)
 def request(self,method='GET',target='/healthz',token=MANAGEMENT,headers=None):
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=1)
  try:
   c.request(method,target,headers={'Authorization':'Bearer '+token,**(headers or {})});r=c.getresponse();return r.status,r.read(),dict(r.getheaders())
  finally:c.close()
 def raw(self,payload):
  with socket.create_connection(('127.0.0.1',self.port),timeout=1) as s:
   s.sendall(payload);data=b''
   try:
    while True:
     chunk=s.recv(65536)
     if not chunk:break
     data+=chunk
   except ConnectionResetError:pass
   return data
 def test_management_auth_actual_health(self):
  status,body,headers=self.request();self.assertEqual((status,body),(200,b'ok\n'));self.assertEqual(self.calls,1);self.assertEqual(headers['Connection'],'close')
 def test_backend_role_denied(self):self.assertEqual(self.request(token=BACKEND)[0],401);self.assertEqual(self.calls,0)
 def test_storage_role_denied(self):self.assertEqual(self.request(token=STORAGE)[0],401);self.assertEqual(self.calls,0)
 def test_raw_double_slash_denied(self):
  data=self.raw(b'GET //healthz HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+MANAGEMENT.encode()+b'\r\n\r\n');self.assertTrue(data.startswith(b'HTTP/1.1 400'));self.assertEqual(self.calls,0)
 def test_head_not_supported_and_does_not_probe(self):
  self.assertEqual(self.request(method='HEAD')[0],405);self.assertEqual(self.calls,0)
 def test_query_denied(self):self.assertEqual(self.request(target='/healthz?secret=fixture')[0],400);self.assertEqual(self.calls,0)
 def test_unauthorized_body_not_read(self):
  start=time.monotonic();self.assertEqual(self.request(token='wrong',headers={'Content-Length':'100'})[0],401);self.assertLess(time.monotonic()-start,0.2);self.assertEqual(self.calls,0)
 def test_duplicate_auth_denied(self):
  payload=b'GET /healthz HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+MANAGEMENT.encode()+b'\r\nAuthorization: Bearer '+MANAGEMENT.encode()+b'\r\n\r\n';self.assertTrue(self.raw(payload).startswith(b'HTTP/1.1 401'));self.assertEqual(self.calls,0)
 def test_unknown_method_auth_first(self):self.assertEqual(self.request(method='UNKNOWN',token='wrong')[0],401);self.assertEqual(self.calls,0)
 def test_newline_key_configuration_denied(self):
  server=None
  try:
   with self.assertRaisesRegex(ValueError,'^Invalid readiness server configuration$'):server=m.create_readiness_server(lambda:True,MANAGEMENT+'\n',BACKEND,STORAGE)
  finally:
   if server:server.server_close()
 def test_oversized_headers_generic_431(self):
  payload=b'GET /healthz HTTP/1.1\r\nHost: fixture\r\nX-Large: '+b'x'*33000+b'\r\n\r\n';self.assertTrue(self.raw(payload).startswith(b'HTTP/1.1 431'));self.assertEqual(self.calls,0)
 def test_authenticated_positive_body_denied_without_read(self):
  self.assertEqual(self.request(headers={'Content-Length':'100'})[0],400);self.assertEqual(self.calls,0)
 def test_malformed_http_error_redacts_raw_version(self):
  data=self.raw(b'GET /healthz HTTP/secret-fixture HTTP-extra\r\nHost: fixture\r\n\r\n');self.assertNotIn(b'secret-fixture',data);self.assertNotIn(b'<html',data.lower());self.assertEqual(self.calls,0)
 def test_noncanonical_length_trailing_space_denied(self):
  self.assertEqual(self.request(headers={'Content-Length':'0 '})[0],400);self.assertEqual(self.calls,0)
 def test_duplicate_lengths_denied(self):
  payload=b'GET /healthz HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+MANAGEMENT.encode()+b'\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n';self.assertTrue(self.raw(payload).startswith(b'HTTP/1.1 400'));self.assertEqual(self.calls,0)
 def test_expect_unauthorized_no_continue_or_body_read(self):
  payload=b'POST /healthz HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer wrong\r\nExpect: 100-continue\r\nContent-Length: 100\r\n\r\n';data=self.raw(payload);self.assertTrue(data.startswith(b'HTTP/1.1 401'));self.assertNotIn(b'100 Continue',data);self.assertEqual(self.calls,0)
 def test_probe_exception_redacted(self):
  def broken():raise RuntimeError('secret-fixture')
  self.server._probe=broken;status,body,_=self.request();self.assertEqual(status,503);self.assertNotIn(b'secret-fixture',body)
 def test_nonbool_truthy_probe_held(self):
  self.server._probe=lambda:1;self.assertEqual(self.request()[0],503)
 def test_connection_capacity_is_bounded_and_permit_recovers(self):
  self.server._semaphore=threading.BoundedSemaphore(1)
  first=socket.create_connection(('127.0.0.1',self.port),timeout=1);first.sendall(b'GET /healthz HTTP/1.1\r\n')
  try:
   deadline=time.monotonic()+0.2
   while self.server._semaphore._value and time.monotonic()<deadline:time.sleep(0.005)
   self.assertEqual(self.server._semaphore._value,0)
   with socket.create_connection(('127.0.0.1',self.port),timeout=1) as second:
    try:received=second.recv(128)
    except ConnectionResetError:received=b''
    self.assertEqual(received,b'')
  finally:first.close()
  deadline=time.monotonic()+0.5
  while not self.server._semaphore._value and time.monotonic()<deadline:time.sleep(0.005)
  self.assertEqual(self.server._semaphore._value,1);self.assertEqual(self.request()[0],200)
 def test_combined_request_and_header_size_bound(self):
  prefix=b'GET /healthz HTTP/1.1\r\nHost: fixture\r\nX-Large: ';payload=prefix+b'x'*(32769-len(prefix)-4)+b'\r\n\r\n';self.assertEqual(len(payload),32769);self.assertTrue(self.raw(payload).startswith(b'HTTP/1.1 431'));self.assertEqual(self.calls,0)
 def test_authorized_expect_never_continues_or_reads_body(self):
  payload=b'POST /healthz HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+MANAGEMENT.encode()+b'\r\nExpect: 100-continue\r\nContent-Length: 100\r\n\r\n';data=self.raw(payload);self.assertTrue(data.startswith(b'HTTP/1.1 400'));self.assertNotIn(b'100 Continue',data);self.assertEqual(self.calls,0)
 def test_authorized_unknown_method_denied_without_html(self):
  status,body,_=self.request(method='UNKNOWN');self.assertEqual(status,405);self.assertNotIn(b'<html',body);self.assertEqual(self.calls,0)
if __name__=='__main__':unittest.main(verbosity=2)
