#!/usr/bin/env python3
"""Authenticated SSH-friendly client for the Snow Gloves fleet pilot."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint',default='http://127.0.0.1:4101')
    parser.add_argument('--token-file')
    sub=parser.add_subparsers(dest='command',required=True)
    submit=sub.add_parser('submit')
    submit.add_argument('--project',required=True)
    submit.add_argument('--brief',required=True)
    submit.add_argument('--title')
    submit.add_argument('--category',default='development')
    submit.add_argument('--runtime',default='codex')
    submit.add_argument('--idempotency-key',default=None)
    submit.add_argument('--parent',help='parent task id; makes this a child task')
    submit.add_argument('--role',help='logical role for a child task (ceo, cto, chief-of-staff, librarian, interpreter, dispatcher, sentinel)')
    submit.add_argument('--stage',help='child stage: plan, reference, review, dispatch or verify')
    sub.add_parser('list')
    for command in ('status','logs','cancel'):
        child=sub.add_parser(command)
        child.add_argument('task_id')
    args=parser.parse_args()
    token=Path(args.token_file).read_text().strip() if args.token_file else os.environ.get('SNOWGLOVES_FLEET_TOKEN','')
    if not token:
        parser.error('Set SNOWGLOVES_FLEET_TOKEN or --token-file')
    path='/v1/tasks'
    body=None
    if args.command=='submit':
        body={key:getattr(args,key) for key in ('project','brief','category','runtime')}
        if args.title:
            body['title']=args.title
        if args.parent:
            body.update(parent_id=args.parent,logical_role=args.role,stage=args.stage)
        elif args.role or args.stage:
            parser.error('--role and --stage require --parent')
        body['idempotency_key']=args.idempotency_key or uuid.uuid4().hex
    elif args.command!='list':
        path+='/'+args.task_id
        if args.command=='logs':
            path+='/events'
        elif args.command=='cancel':
            path+='/cancel'
            body={}
    request=urllib.request.Request(args.endpoint.rstrip('/')+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=100 if args.command == 'submit' else 30) as response:
            print(json.dumps(json.load(response),indent=2))
    except urllib.error.HTTPError as exc:
        print('Fleet request failed: HTTP '+str(exc.code),file=sys.stderr)
        return 1
    except urllib.error.URLError:
        print('Fleet coordinator unavailable',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())
