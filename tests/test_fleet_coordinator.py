import hashlib
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from lib.fleet_coordinator import Coordinator, Rejected, server


@pytest.fixture
def fleet(tmp_path):
    config={'data_root':str(tmp_path/'ops'),'projects':{'snowgloves':{'root':str(tmp_path/'repo'),'tenant':'heyzack','organization':'heyzack','runtimes':['codex']}},'principals':{'founder':{'token':'founder-secret-token','projects':['snowgloves']},'outsider':{'token':'outsider-token','projects':[]}},'workers':{'mac-coding-1':{'token':'worker-secret-token','projects':['snowgloves'],'runtimes':['codex']},'wrong-worker':{'token':'another-worker','projects':['snowgloves'],'runtimes':['codex']}},'capacity':1,'lease_seconds':30,'allowed_origins':['http://127.0.0.1:18760']}
    now=[100.0]
    coordinator=Coordinator(config,clock=lambda:now[0])
    yield coordinator,config,now
    coordinator.close()


def submit(c,config,**updates):
    body={'project':'snowgloves','brief':'Review the code','runtime':'codex','idempotency_key':'test'}
    body.update(updates)
    return c.submit('founder',config['principals']['founder'],body)


def claim(c,config):
    return c.claim('mac-coding-1',config['workers']['mac-coding-1'])


def report(c,config,task,**updates):
    body={'task_id':task['id'],'attempt_id':task['attempt_id'],'lease_token':task['lease_token'],'event_id':'event1','type':'heartbeat'}
    body.update(updates)
    return c.report('mac-coding-1',config['workers']['mac-coding-1'],body)


def test_auth_project_owner_and_runtime(fleet):
    c,conf,_=fleet
    with pytest.raises(Rejected) as exc:
        c.authenticate('bad')
    assert exc.value.status==401
    with pytest.raises(Rejected):
        c.authenticate(conf['workers']['mac-coding-1']['token'])
    with pytest.raises(Rejected):
        submit(c,conf,project='private')
    with pytest.raises(Rejected):
        submit(c,conf,runtime='claude')
    task=submit(c,conf)
    with pytest.raises(Rejected) as exc:
        c.detail('outsider',conf['principals']['outsider'],task['id'])
    assert exc.value.status==404
    assert 'root' not in task and 'lease_token' not in task


def test_idempotency_capacity_and_cancellation(fleet):
    c,conf,_=fleet
    task=submit(c,conf)
    assert submit(c,conf)['id']==task['id']
    with pytest.raises(Rejected) as exc:
        submit(c,conf,brief='Different request')
    assert exc.value.status==409
    running=claim(c,conf)
    second=submit(c,conf,idempotency_key='second')
    assert claim(c,conf) is None
    owner=conf['principals']['founder']
    assert c.cancel('founder',owner,second['id'])['status']=='cancelled'
    assert c.cancel('founder',owner,task['id'])['status']=='cancel_requested'
    assert report(c,conf,running)['cancel_requested']
    assert report(c,conf,running,event_id='cancel',type='cancelled')['accepted']
    assert c.detail('founder',owner,task['id'])['status']=='cancelled'


def test_forged_worker_and_duplicate_events(fleet):
    c,conf,_=fleet
    submit(c,conf)
    task=claim(c,conf)
    with pytest.raises(Rejected):
        report(c,conf,task,lease_token='forged')
    body={'task_id':task['id'],'attempt_id':task['attempt_id'],'lease_token':task['lease_token'],'event_id':'forged','type':'heartbeat'}
    with pytest.raises(Rejected):
        c.report('wrong-worker',conf['workers']['wrong-worker'],body)
    assert not report(c,conf,task)['duplicate']
    assert report(c,conf,task)['duplicate']
    assert len(c.detail('founder',conf['principals']['founder'],task['id'],True))==1


def test_restart_and_expired_lease_are_not_replayed(fleet):
    c,conf,now=fleet
    submit(c,conf)
    task=claim(c,conf)
    second=Coordinator(conf,clock=lambda:now[0])
    try:
        assert second.claim('mac-coding-1',conf['workers']['mac-coding-1']) is None
        assert report(second,conf,task)['accepted']
        now[0]+=31
        result=second.detail('founder',conf['principals']['founder'],task['id'])
        assert result['status']=='interrupted'
        assert claim(second,conf) is None
        with pytest.raises(Rejected) as exc:
            report(second,conf,task,event_id='late')
        assert exc.value.status==409
    finally:
        second.close()


def test_redaction(fleet):
    c,conf,_=fleet
    submit(c,conf,brief='Bearer secret123 api_key=secretABC founder-secret-token sk-123abc')
    task=claim(c,conf)
    assert all(secret not in task['brief'] for secret in ('secret123','secretABC','founder-secret-token','sk-123abc'))
    report(c,conf,task,type='log',message='Bearer abc worker-secret-token '+task['lease_token'])
    events=c.detail('founder',conf['principals']['founder'],task['id'],True)
    assert 'worker-secret-token' not in events[0]['message']
    assert task['lease_token'] not in events[0]['message']


def test_verified_artifact_and_path_escape(fleet,tmp_path):
    c,conf,_=fleet
    submit(c,conf)
    task=claim(c,conf)
    artifact=c.artifacts/'result.json'
    artifact.write_text('{"result":"ok"}')
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    outside=tmp_path/'outside'
    outside.write_text('outside')
    for path,sha in ((str(outside),digest),('../outside',digest),(str(artifact),'bad')):
        with pytest.raises(Rejected):
            report(c,conf,task,type='succeeded',artifact={'path':path,'sha256':sha})
    symlink=c.artifacts/'link'
    symlink.symlink_to(outside)
    with pytest.raises(Rejected):
        report(c,conf,task,type='succeeded',artifact={'path':str(symlink),'sha256':digest})
    assert report(c,conf,task,type='succeeded',artifact={'path':str(artifact),'sha256':digest})['accepted']
    assert report(c,conf,task,type='succeeded',artifact={'path':str(artifact),'sha256':digest})['duplicate']
    result=c.detail('founder',conf['principals']['founder'],task['id'])
    assert result['status']=='succeeded'
    assert result['artifact']=={'path':'result.json','sha256':digest}


def test_atomic_claim_from_concurrent_threads(fleet):
    c,conf,_=fleet
    submit(c,conf)
    submit(c,conf,idempotency_key='second')
    claims=[]
    threads=[threading.Thread(target=lambda:claims.append(claim(c,conf))) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([task for task in claims if task])==1


def test_http_bounds_auth_origin_and_worker_separation(fleet):
    c,conf,_=fleet
    http=server(c,0)
    thread=threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    endpoint='http://127.0.0.1:'+str(http.server_port)
    def request(path,token=None,body=None,**headers):
        headers={'Content-Type':'application/json',**headers}
        if token:
            headers['Authorization']='Bearer '+token
        req=urllib.request.Request(endpoint+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(req,timeout=3) as response:
            return json.load(response)
    try:
        assert request('/healthz')['ok']
        for path,token,headers,code in (
            ('/v1/tasks',None,{},401),
            ('/v1/tasks','worker-secret-token',{},401),
            ('/v1/tasks','founder-secret-token',{'Origin':'https://evil.example'},403),
            ('/v1/tasks?token=secret','founder-secret-token',{},400),
            ('/v1/tasks','founder-secret-token',{'Host':'evil.example'},403)):
            with pytest.raises(urllib.error.HTTPError) as exc:
                request(path,token,**headers)
            assert exc.value.code==code
        result=request('/v1/tasks','founder-secret-token',{'project':'snowgloves','brief':'Review','idempotency_key':'http'})
        assert request('/v1/tasks/'+result['id'],'founder-secret-token')['id']==result['id']
        task=request('/v1/worker/claim','worker-secret-token',{})['task']
        assert task['root']==conf['projects']['snowgloves']['root']
    finally:
        http.shutdown()
        http.server_close()


def test_hermes_bridge_interprets_after_authorization_and_cannot_override_scope(fleet):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    c,conf,_=fleet
    calls=[]
    class Bridge(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            calls.append((self.path,self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            payload=json.dumps({'title':'Interpreted task','brief':'Run the allowed review','category':'engineering','logical_role':'cto','summary':'Task structured','hermes_revision':'pinned-revision','project':'private','root':'/etc','runtime':'shell','owner':'outsider'}).encode()
            self.send_response(200)
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    bridge=ThreadingHTTPServer(('127.0.0.1',0),Bridge)
    threading.Thread(target=bridge.serve_forever,daemon=True).start()
    conf['hermes_bridge']={'url':f'http://127.0.0.1:{bridge.server_port}','token':'bridge-secret-token','timeout':3}
    try:
        with pytest.raises(Rejected):
            submit(c,conf,project='private')
        assert not calls
        task=submit(c,conf)
        assert task['title']=='Interpreted task'
        assert task['project']=='snowgloves' and task['runtime']=='codex' and task['owner']=='founder'
        assert task['logical_role']=='cto' and task['organization']=='heyzack' and task['session_id']==task['id']
        assert len(calls)==1 and calls[0][1]=='Bearer bridge-secret-token'
        assert submit(c,conf)['id']==task['id']
        assert len(calls)==1
        events=c.detail('founder',conf['principals']['founder'],task['id'],True)
        assert events[0]['type']=='hermes_interpreted'
        assert json.loads(events[0]['message'])['hermes_revision']=='pinned-revision'
        claimed=claim(c,conf)
        assert claimed['root']==conf['projects']['snowgloves']['root']
    finally:
        bridge.shutdown()
        bridge.server_close()


def test_failed_bridge_never_dispatches(fleet):
    c,conf,_=fleet
    conf['hermes_bridge']={'url':'http://127.0.0.1:1','token':'bridge-token','timeout':0.1}
    with pytest.raises(Rejected) as exc:
        submit(c,conf)
    assert exc.value.status==503
    assert not c.list_tasks('founder',conf['principals']['founder'])
    assert claim(c,conf) is None
