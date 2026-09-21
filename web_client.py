#!/usr/bin/env python3
"""Administrative CLI for the durable outbound web queue.

The autonomous service imports local_queue directly. Legacy manual commands
remain available for diagnostics and recovery, not as a managing Codex task.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from bridge import BridgeError, exclusive
from cloud_client import API, Conflict, STATE


from local_queue import Queue


def wait_for_request(queue,api,timeout=50,interval=5):
    """Wait for work without invoking a model or dispatching anything.

    A running Codex turn can await this command and use its existing app tools
    after it returns. This does not wake an idle or stopped Codex task.
    """
    if not 1<=timeout<=300 or not 1<=interval<=30:
        raise BridgeError('Invalid polling interval or timeout')
    deadline=time.monotonic()+timeout
    while True:
        queue.tick(api)
        pending=queue.pending()
        if pending['messages']:return {'status':'ready',**pending}
        remaining=deadline-time.monotonic()
        if remaining<=0:return {'status':'timeout','messages':[]}
        time.sleep(min(interval,remaining))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, default=STATE)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('tick', 'pending', 'status'): sub.add_parser(name)
    wait=sub.add_parser('wait');wait.add_argument('--timeout',type=int,default=50);wait.add_argument('--interval',type=int,default=5)
    catalog = sub.add_parser('catalog'); catalog.add_argument('file', type=Path)
    begin = sub.add_parser('begin'); begin.add_argument('id', type=int); begin.add_argument('--thread', required=True); begin.add_argument('--baseline', required=True)
    sent = sub.add_parser('sent'); sent.add_argument('id', type=int); sent.add_argument('--marker', required=True)
    publish = sub.add_parser('publish'); publish.add_argument('id', type=int); publish.add_argument('file', type=Path)
    collect = sub.add_parser('collect'); collect.add_argument('id',type=int); collect.add_argument('--source-thread',required=True); collect.add_argument('--turn',required=True)
    args = parser.parse_args()
    try:
        config = json.loads((args.state / 'web.json').read_text())
        if config.get('paused', True):
            print(json.dumps({'status': 'paused', 'messages': []})); return 0
        with exclusive(args.state):
            with Queue(args.state) as queue:
                if args.command == 'catalog':
                    catalog = json.loads(args.file.read_text())
                    if catalog.get('project_id') != config['project_id']:
                        raise BridgeError('Project mismatch')
                    result = API(config).call('/v2/catalog', catalog)
                elif args.command == 'tick': result = queue.tick(API(config))
                elif args.command == 'pending': result = queue.pending()
                elif args.command == 'wait': result = wait_for_request(queue,API(config),args.timeout,args.interval)
                elif args.command == 'begin': result = queue.begin(args.id,args.thread,args.baseline,api=API(config))
                elif args.command == 'sent': queue.sent(args.id,args.marker); result = {'status':'dispatched'}
                elif args.command == 'collect':
                    from rollout_response import locate,recover
                    row=queue.db.execute('SELECT * FROM requests WHERE id=?',(args.id,)).fetchone()
                    if not row or row['status']!='dispatched':raise BridgeError('Request not dispatched')
                    dispatch=json.loads(row['dispatch'])
                    root=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'sessions'
                    body=recover(locate(root,dispatch['thread']),dispatch['thread'],dispatch['marker'],args.source_thread,args.turn)
                    result=queue.publish(args.id,body) if body else {'status':'waiting_for_correlated_reply'}
                elif args.command == 'publish': result = queue.publish(args.id,json.loads(args.file.read_text()))
                else: result = queue.status()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (BridgeError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        print(str(exc) if isinstance(exc,BridgeError) else 'Website collector error; details hidden',file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
