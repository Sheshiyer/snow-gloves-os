#!/usr/bin/env python3
"""Authenticated SSH-friendly client for the Snow Gloves fleet pilot."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import uuid

from lib.fleet_business import COMMERCIAL_PREPARATION_CATEGORY


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint',default='http://127.0.0.1:4101')
    parser.add_argument('--token-file')
    sub=parser.add_subparsers(dest='command',required=True)
    submit=sub.add_parser('submit')
    submit.add_argument('--project',required=True)
    submit.add_argument('--brief',required=True)
    submit.add_argument('--title')
    submit.add_argument('--category')
    submit.add_argument('--runtime',default='codex')
    submit.add_argument('--idempotency-key',default=None)
    submit.add_argument('--parent',help='parent task id; makes this a child task')
    submit.add_argument('--role',help='logical role for a child task (ceo, cto, chief-of-staff, librarian, interpreter, dispatcher, sentinel)')
    submit.add_argument('--domain-role',help='business template id; stored only in --context-file')
    submit.add_argument('--context-file',help='JSON business context file (snowgloves.business-context.v1)')
    submit.add_argument('--supersedes',help='id of a failed child of --parent to retry (same role and stage)')
    submit.add_argument('--access',choices=('read','write'),help='write needs a CTO child under --parent and explicit server-side enablement')
    submit.add_argument('--stage',help='child stage: plan, reference, review, dispatch or verify')
    submit.add_argument('--review-of',help='verified succeeded CTO write-child id for a manual Sentinel review')
    sub.add_parser('list')
    for command in ('status','logs','cancel'):
        child=sub.add_parser(command)
        child.add_argument('task_id')
    fanout=sub.add_parser('fanout',help='ask the authorized Chief-of-Staff planner for bounded read-only children')
    fanout.add_argument('task_id')
    args=parser.parse_args()
    token=Path(args.token_file).read_text().strip() if args.token_file else os.environ.get('SNOWGLOVES_FLEET_TOKEN','')
    if not token:
        parser.error('Set SNOWGLOVES_FLEET_TOKEN or --token-file')
    path='/v1/tasks'
    body=None
    if args.command=='submit':
        business_context = None
        if args.context_file:
            try:
                business_context = json.loads(Path(args.context_file).read_text())
            except (OSError, ValueError):
                parser.error('--context-file must name a readable JSON file')
            if not isinstance(business_context,dict):
                parser.error('--context-file must contain a JSON object')
            if args.domain_role:
                existing = business_context.get('domain_role')
                if existing is not None and (
                        not isinstance(existing,str) or existing.strip() != args.domain_role.strip()):
                    parser.error('--domain-role conflicts with context-file domain_role')
                business_context['domain_role'] = args.domain_role
        elif args.domain_role:
            parser.error('--domain-role requires --context-file')
        if business_context is not None and args.category not in (None, COMMERCIAL_PREPARATION_CATEGORY):
            parser.error('business context requires --category commercial-preparation')
        body={key:getattr(args,key) for key in ('project','brief','runtime')}
        if args.category or business_context is not None or not args.parent:
            body['category'] = args.category or (COMMERCIAL_PREPARATION_CATEGORY if business_context is not None else 'development')
        if business_context is not None:
            body['business_context'] = business_context
        if args.title:
            body['title']=args.title
        if args.parent:
            body.update(parent_id=args.parent,logical_role=args.role,stage=args.stage)
            if args.supersedes:
                body['supersedes']=args.supersedes
            if args.access:
                body['access']=args.access
            if args.review_of is not None:
                if (not re.fullmatch(r'[a-f0-9]{32}', args.review_of) or args.role != 'sentinel'
                        or args.stage != 'verify' or args.access == 'write'):
                    parser.error('--review-of requires a 32-hex source id and a read-only Sentinel verify child')
                body['review_of']=args.review_of
        elif args.role or args.stage or args.supersedes or args.access or args.review_of is not None:
            parser.error('--role, --stage, --supersedes, --access and --review-of require --parent')
        body['idempotency_key']=args.idempotency_key or uuid.uuid4().hex
    elif args.command!='list':
        path+='/'+args.task_id
        if args.command=='logs':
            path+='/events'
        elif args.command=='cancel':
            path+='/cancel'
            body={}
        elif args.command=='fanout':
            path+='/fanout'
            body={}
    request=urllib.request.Request(args.endpoint.rstrip('/')+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=100 if args.command in ('submit','fanout') else 30) as response:
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
