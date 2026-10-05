import unittest,json,hashlib
from lib import runtime_operation_identity as m
class Review(unittest.TestCase):
 def setUp(self):
  self.context={'instanceId':'heyzack','runtimeVersion':'3.8.50','imageDigest':'a'*64,'keyId':'owned-fixture-key'};self.job='b'*32;self.source='c'*32;self.source_digest='d'*64;self.artifact={'leaf':'sg-encrypted-'+self.source+'.bin','bytes':2027740,'sha256':'e'*64}
 def checkpoint(self):return {'job_id':self.job,'request_digest':m.checkpoint_digest(self.context,self.job)}
 def restore(self):return {'restore_job_id':self.job,'source_checkpoint_job_id':self.source,'source_request_digest':self.source_digest,**self.artifact,'request_digest':m.restore_digest(self.context,self.job,self.source,self.source_digest,self.artifact)}
 def test_checkpoint_canonical_preimage(self):
  expected={'schema':'sg.operation-request.v1','operation':'checkpoint','context':self.context,'request':{'job_id':self.job}};digest=hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest();self.assertEqual(m.checkpoint_digest(self.context,self.job),digest);self.assertEqual(m.validate_checkpoint(self.context,self.checkpoint()),self.checkpoint())
 def test_restore_valid_distinct_source_identity(self):
  self.assertEqual(m.validate_restore(self.context,self.restore()),self.restore())
 def test_checkpoint_digest_cannot_authorize_restore(self):
  p=self.restore();p['request_digest']=self.checkpoint()['request_digest']
  with self.assertRaises(ValueError):m.validate_restore(self.context,p)
 def test_context_change_denies_reuse(self):
  p=self.checkpoint()
  for k,v in [('instanceId','other'),('imageDigest','f'*64),('keyId','new-key')]:
   with self.subTest(k=k):
    context={**self.context,k:v}
    with self.assertRaises(ValueError):m.validate_checkpoint(context,p)
 def test_restore_input_change_denies_reuse(self):
  p=self.restore()
  for k,v in [('bytes',32),('sha256','f'*64),('source_request_digest','f'*64),('restore_job_id','f'*32)]:
   with self.subTest(k=k):
    with self.assertRaises(ValueError):m.validate_restore(self.context,{**p,k:v})
 def test_source_leaf_mismatch_denied(self):
  with self.assertRaises(ValueError):m.restore_digest(self.context,self.job,self.source,self.source_digest,{**self.artifact,'leaf':'sg-encrypted-'+'f'*32+'.bin'})
 def test_same_job_restore_denied(self):
  with self.assertRaises(ValueError):m.restore_digest(self.context,self.source,self.source,self.source_digest,self.artifact)
 def test_extra_payload_fields_denied(self):
  with self.assertRaises(ValueError):m.validate_checkpoint(self.context,{**self.checkpoint(),'upstream':'evil'})
 def test_bool_size_and_newline_id_denied(self):
  with self.assertRaises(ValueError):m.restore_digest(self.context,self.job,self.source,self.source_digest,{**self.artifact,'bytes':True})
  with self.assertRaises(ValueError):m.checkpoint_digest(self.context,self.job+'\n')
 def test_dict_subclass_denied(self):
  class Hostile(dict):pass
  with self.assertRaises(ValueError):m.validate_checkpoint(Hostile(self.context),self.checkpoint())
 def test_return_does_not_mutate_inputs(self):
  p=self.restore();before=json.dumps(p);r=m.validate_restore(self.context,p);r['sha256']='f'*64;self.assertEqual(json.dumps(p),before)
 def test_runtime_version_custom_object_denied(self):
  class Equal:
   def __eq__(self,other):return True
   def __ne__(self,other):return False
  with self.assertRaises(ValueError):m.checkpoint_digest({**self.context,'runtimeVersion':Equal()},self.job)
 def test_restore_canonical_preimage(self):
  p=self.restore();request={k:v for k,v in p.items() if k!='request_digest'};expected={'schema':'sg.operation-request.v1','operation':'restore','context':self.context,'request':request};self.assertEqual(p['request_digest'],hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest())
if __name__=='__main__':unittest.main(verbosity=2)
