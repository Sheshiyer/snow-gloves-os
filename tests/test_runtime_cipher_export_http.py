import unittest,pathlib,tempfile,os,json,hashlib,sys,threading,http.client,socket,time
from unittest.mock import patch
from lib.runtime_cipher_export import CheckpointExportReader
from lib.runtime_operation_identity import checkpoint_digest
from lib import runtime_management_http as mh
from lib import runtime_managed_http as proxy
@unittest.skipUnless(sys.platform=='linux','Linux only')
class Proof(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.d=pathlib.Path(self.t.name);self.d.chmod(0o700);self.ctx={'instanceId':'owned','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'owned'};self.job='b'*32;self.payload={'job_id':self.job,'request_digest':checkpoint_digest(self.ctx,self.job)};self.key='m'*40;self.calls=[];self.f=self.d/('sg-encrypted-'+self.job+'.bin');self.j=self.d/('sg-job-'+self.job+'.json');self.fixture(b'x'*70000)
  self.server=mh.create_management_server(self.callback,self.callback,self.key,'b'*40,'s'*40,operation_context=self.ctx,export_cb=self.reader,connection_timeout=0.3);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.port=self.server.server_address[1]
 def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(2);self.t.cleanup()
 def fixture(self,data):
  self.data=data;self.f.write_bytes(data);self.f.chmod(0o600);self.record={'schema':'sg.local-job.v1','job_id':self.job,'request_digest':self.payload['request_digest'],'state':'artifact-verified','artifact':{'leaf':self.f.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}};self.j.write_text(json.dumps(self.record,separators=(',',':')));self.j.chmod(0o600);s=self.d.stat();self.identity=(s.st_dev,s.st_ino,s.st_uid,0o700)
 def callback(self,p):self.calls.append(p);return {'state':'local-only'}
 def reader(self,p):return CheckpointExportReader(str(self.d),self.identity,self.ctx,p)
 def request(self,key=None,path='/_management/export',method='POST',payload=None,headers=None):
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=4);h={'Authorization':'Bearer '+(self.key if key is None else key),'Content-Type':'application/json'};h.update(headers or {});c.request(method,path,json.dumps(self.payload if payload is None else payload),h);r=c.getresponse();status=r.status;rh=dict(r.getheaders());body=r.read();c.close();return status,rh,body
 def test_valid(self):
  status,h,b=self.request();self.assertEqual(status,200);self.assertEqual(b,self.data);self.assertEqual(json.loads(h['X-SG-Export-Context']),self.ctx);self.assertEqual(json.loads(h['X-SG-Export-Record']),self.record);self.assertEqual(h['X-SG-Export-Digest'],hashlib.sha256(b).hexdigest());self.assertEqual(h['Content-Type'],'application/vnd.sg.cipher-export+v1');self.assertEqual(self.calls,[])
 def test_roles(self):
  for key in ['b'*40,'s'*40,'z'*40]:self.assertEqual(self.request(key=key)[0],401)
 def test_bad_digest(self):self.assertEqual(self.request(payload={**self.payload,'request_digest':'f'*64})[0],400)
 def test_missing(self):self.j.unlink();self.assertEqual(self.request()[0],503)
 def test_corrupt(self):self.f.write_bytes(b'y'*len(self.data));self.assertEqual(self.request()[0],503)
 def test_none(self):self.server.export_cb=None;self.assertEqual(self.request()[0],503);self.assertEqual(self.request(path='/_management/checkpoint')[0],200)
 def test_invalid_result(self):self.server.export_cb=lambda p:object();self.assertEqual(self.request()[0],503);self.assertEqual(self.request(path='/_management/checkpoint')[0],200)
 def test_busy(self):
  token=self.server.gate.begin_stream()
  try:self.assertEqual(self.request()[0],409)
  finally:self.server.gate.end_stream(token)
  self.assertEqual(self.request()[0],200)
 def test_wrong_method_role(self):self.assertEqual(self.request(method='GET',key='b'*40)[0],401);self.assertEqual(self.request(method='GET')[0],405)
 def test_paths(self):
  for path in ['/_management/export?q=1','//_management/export','/_management/%65xport']:self.assertEqual(self.request(path=path)[0],400)
 def test_body_framing(self):
  for headers in [{'Content-Length':'2049'},{'Content-Length':'01'},{'Content-Type':'application/json-foreign'},{'Transfer-Encoding':'chunked'},{'Expect':'100-continue'}]:self.assertEqual(self.request(headers=headers)[0],400)
 def test_factory_failure(self):
  def fail(p):raise RuntimeError('secret diagnostic')
  self.server.export_cb=fail;status,h,b=self.request();self.assertEqual(status,503);self.assertNotIn(b'secret',b);token=self.server.gate.begin_stream();self.server.gate.end_stream(token)
 def test_auth_before_body(self):
  c=socket.create_connection(('127.0.0.1',self.port),timeout=2)
  try:c.sendall(b'POST /_management/export HTTP/1.1\r\nHost: fixture\r\nContent-Length: 100\r\nContent-Type: application/json\r\n\r\n');self.assertIn(b'401',c.recv(4096))
  finally:c.close()
 def test_zero_effects(self):
  before={p.name:p.read_bytes() for p in self.d.iterdir()};self.assertEqual(self.request()[0],200);self.assertEqual(before,{p.name:p.read_bytes() for p in self.d.iterdir()})
 def test_midstream_cipher_tamper(self):
  original=CheckpointExportReader.iter_chunks
  def tamper(r):
   it=original(r)
   try:
    yield next(it)
    with self.f.open('r+b') as f:f.seek(69999);f.write(b'y')
    yield from it
   finally:it.close()
  c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
  try:
   with patch.object(CheckpointExportReader,'iter_chunks',tamper):
    c.request('POST','/_management/export',json.dumps(self.payload),{'Authorization':'Bearer '+self.key,'Content-Type':'application/json'});r=c.getresponse();self.assertEqual(r.status,200)
    with self.assertRaises(http.client.IncompleteRead) as cm:r.read()
    self.assertEqual(len(cm.exception.partial),65536);self.assertNotIn(b'HTTP/',cm.exception.partial)
  finally:c.close()
  token=self.server.gate.begin_stream();self.server.gate.end_stream(token)
 def test_max_cipher(self):
  self.fixture(b'x'*(64*1024*1024+4136));status,h,b=self.request();self.assertEqual(status,200);self.assertEqual(len(b),len(self.data));self.assertEqual(hashlib.sha256(b).hexdigest(),self.record['artifact']['sha256'])
 def test_mismatched_manifest(self):
  original=CheckpointExportReader.manifest
  def wrong(r):ctx,rec=original(r);ctx['keyId']='other';return ctx,rec
  with patch.object(CheckpointExportReader,'manifest',wrong):self.assertEqual(self.request()[0],503)
 def test_subclass_rejected(self):
  class Other(CheckpointExportReader):pass
  self.server.export_cb=lambda p:Other(str(self.d),self.identity,self.ctx,p);self.assertEqual(self.request()[0],503)
 def test_delayed_factory(self):
  now=[time.monotonic()];original=self.reader
  def late(p):r=original(p);now[0]+=16;return r
  self.server.export_cb=late
  with patch.object(mh.time,'monotonic',side_effect=lambda:now[0]):self.assertEqual(self.request()[0],503)
  token=self.server.gate.begin_stream();self.server.gate.end_stream(token)
 def test_header_deadline(self):
  now=[time.monotonic()];send_header=mh._ManagementHandler.send_header
  def late(handler,key,val):
   result=send_header(handler,key,val)
   if key=='X-SG-Export-Digest':now[0]+=16
   return result
  c=socket.create_connection(('127.0.0.1',self.port),timeout=3)
  try:
   raw=json.dumps(self.payload).encode();request=('POST /_management/export HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+self.key+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw))+'\r\n\r\n').encode()+raw
   with patch.object(mh.time,'monotonic',side_effect=lambda:now[0]),patch.object(mh._ManagementHandler,'send_header',late):c.sendall(request);body=c.recv(4096);self.assertEqual(body,b'')
  finally:c.close()
 def test_blocked_client_deadline_releases(self):
  self.fixture(b'x'*(64*1024*1024+4136));c=socket.socket();c.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024);c.settimeout(3);c.connect(('127.0.0.1',self.port));raw=json.dumps(self.payload).encode();request=('POST /_management/export HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+self.key+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw))+'\r\n\r\n').encode()+raw;start=time.monotonic();c.sendall(request);self.assertIn(b'200',c.recv(1024))
  try:
   self.assertRaises(RuntimeError,self.server.gate.begin_stream)
   deadline=start+18;released=False
   while time.monotonic()<deadline:
    try:token=self.server.gate.begin_stream();self.server.gate.end_stream(token);released=True;break
    except RuntimeError:time.sleep(0.05)
   self.assertTrue(released);self.assertGreater(time.monotonic()-start,10);self.assertLess(time.monotonic()-start,17)
   import fcntl
   fd=os.open(self.d,os.O_RDONLY|os.O_DIRECTORY)
   try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   finally:os.close(fd)
  finally:c.close()
 def test_client_disconnect_releases(self):
  self.fixture(b'x'*(64*1024*1024+4136));c=socket.create_connection(('127.0.0.1',self.port),timeout=3);raw=json.dumps(self.payload).encode();c.sendall(('POST /_management/export HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+self.key+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw))+'\r\n\r\n').encode()+raw);self.assertIn(b'200',c.recv(1024));c.close();deadline=time.monotonic()+3;released=False
  while time.monotonic()<deadline:
   try:token=self.server.gate.begin_stream();self.server.gate.end_stream(token);released=True;break
   except RuntimeError:time.sleep(0.02)
  self.assertTrue(released)
 def test_bad_factory_before_bind(self):
  with patch.object(mh._ManagementServer,'server_bind',side_effect=AssertionError('bound')):
   with self.assertRaises(ValueError):mh.create_management_server(self.callback,self.callback,self.key,'b'*40,'s'*40,operation_context=self.ctx,export_cb=object())
 def test_managed_proxy_export_role(self):
  self.server.RequestHandlerClass=proxy._ManagedProxyHandler;self.server.backend_key='b'*40;self.server.health_probe=lambda:True;self.server.admission_probe=lambda:False;self.server.upstream_port=1
  self.assertEqual(self.request()[0],200);self.assertEqual(self.request(method='GET',key='b'*40)[0],401);self.assertEqual(self.request(method='GET')[0],405)
 def test_cleanup_fault_no_second_status(self):
  end=self.server.gate.end_mutation
  def fail():end();raise RuntimeError('cleanup diagnostic')
  c=socket.create_connection(('127.0.0.1',self.port),timeout=3);raw=json.dumps(self.payload).encode();request=('POST /_management/export HTTP/1.1\r\nHost: fixture\r\nAuthorization: Bearer '+self.key+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw))+'\r\n\r\n').encode()+raw
  try:
   with patch.object(self.server.gate,'end_mutation',side_effect=fail):
    c.sendall(request);parts=[]
    while True:
     b=c.recv(65536)
     if not b:break
     parts.append(b)
    response=b''.join(parts);self.assertEqual(response.count(b'HTTP/1.0 '),1);self.assertNotIn(b'cleanup diagnostic',response)
  finally:c.close()
if __name__=='__main__':unittest.main(verbosity=2)
