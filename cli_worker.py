#!/usr/bin/env python3
"""Outbound collector using the installed CLI to resume approved local tasks."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from bridge import BridgeError, exclusive
from cli_session import snapshot, command
from cloud_client import API, STATE
from rollout_response import locate, recover_cli
from web_client import Queue


def collect(queue, home, row):
    dispatch = json.loads(row['dispatch'])
    if dispatch.get('transport') not in ('cli','shared','shared_probe'):
        return False
    reply = recover_cli(locate(home/'sessions',dispatch['thread']), dispatch['thread'],
                        dispatch['prompt'], dispatch['baseline'])
    if reply is None:
        return False
    if row['status'] == 'dispatching':
        queue.sent(row['id'],dispatch['marker'])
    queue.publish(row['id'],{**reply,'marker':dispatch['marker']})
    return True


def request_text(request):
    prompt=request['text']
    if request['files']:
        prompt += '\n\nВложения:\n' + '\n'.join(
            json.dumps({'name': f['name'], 'path': f['path']}, ensure_ascii=False)
            for f in request['files'])
    return prompt


async def dispatch_shared(queue, home, socket, catalog, client_factory=None, *, api):
    from shared_rpc import SharedRPC
    client_factory=client_factory or SharedRPC
    for row in queue.db.execute("SELECT * FROM requests WHERE status IN ('dispatching','dispatched')").fetchall():
        collect(queue,home,row)
    allowed={t['id'] for t in catalog['threads'] if not t.get('read_only',False)}
    pending=[m for m in queue.pending()['messages'] if m['local_status']=='pending' and m['thread'] in allowed]
    waiting=[]
    if pending:
        async with client_factory(socket) as client:
            for item in pending:
                unresolved=queue.db.execute("SELECT 1 FROM requests WHERE status IN ('dispatching','dispatched') AND json_extract(payload,'$.thread')=?",(item['thread'],)).fetchone()
                if unresolved:
                    continue
                metadata=await client.call('thread/read',{'threadId':item['thread'],'includeTurns':False})
                if metadata['thread']['status']['type'] not in ('idle','notLoaded'):
                    waiting.append({'id':item['id'],'reason':'task_active'})
                    continue
                before=snapshot(home,item['thread'],require_unowned=False)
                resumed=await client.call('thread/resume',{'threadId':item['thread'],'excludeTurns':True})
                if resumed['thread']['status']['type']!='idle':
                    waiting.append({'id':item['id'],'reason':'task_active'})
                    continue
                after=snapshot(home,item['thread'],require_unowned=False)
                if before['settings']!=after['settings']:
                    raise BridgeError('Shared resume changed task settings; dispatch stopped')
                request=queue.begin(item['id'],item['thread'],after['baseline'],api=api)
                prompt=request_text(request)
                with queue.db:
                    row=queue.db.execute('SELECT dispatch FROM requests WHERE id=?',(item['id'],)).fetchone()
                    dispatch=json.loads(row['dispatch'])
                    dispatch.update(transport='shared',prompt=prompt,settings=after['settings'])
                    queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
                started=await client.call('turn/start',{'threadId':item['thread'],'input':[{'type':'text','text':prompt}]})
                turn=started['turn']['id']
                with queue.db:
                    dispatch['turn_id']=turn
                    queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
                queue.sent(item['id'],request['marker'])
                try:
                    await client.wait_completed(item['thread'],turn)
                except TimeoutError:
                    # The accepted turn may still be running. Keep its durable ID
                    # and collect the persisted reply on later polling cycles.
                    return {'status':'awaiting_completion','id':item['id']}
                row=queue.db.execute('SELECT * FROM requests WHERE id=?',(item['id'],)).fetchone()
                matched=collect(queue,home,row)
                return {'status':'completed' if matched else 'awaiting_persisted_reply','id':item['id']}
    unresolved=[row['id'] for row in queue.db.execute("SELECT id FROM requests WHERE status IN ('dispatching','dispatched')")]
    if unresolved:
        return {'status':'needs_reconciliation','ids':unresolved}
    return {'status':'waiting_for_tasks','requests':waiting} if waiting else {'status':'idle'}


def dispatch_one(queue, home, executable, catalog, run=subprocess.run, *, api):
    # Recover first. An interrupted dispatch is never submitted a second time.
    for row in queue.db.execute("SELECT * FROM requests WHERE status IN ('dispatching','dispatched')").fetchall():
        collect(queue,home,row)
    allowed = {item['id']:item for item in catalog['threads'] if not item.get('read_only',False)}
    waiting=[]
    for item in queue.pending()['messages']:
        if item['local_status'] != 'pending' or item['thread'] not in allowed:
            continue
        unresolved = queue.db.execute("SELECT 1 FROM requests WHERE status IN ('dispatching','dispatched') AND json_extract(payload,'$.thread')=?",(item['thread'],)).fetchone()
        if unresolved:
            continue
        try:
            state = snapshot(home,item['thread'])
            if state['status'] != 'ready':
                waiting.append({'id':item['id'],'reason':'desktop_writer_lock'})
                continue
            args = command(executable,state)
        except (BridgeError,OSError,ValueError,KeyError):
            # One unsupported task must not stop unrelated approved requests.
            # No dispatch intent is created until settings can be preserved.
            waiting.append({'id':item['id'],'reason':'task_settings_unavailable'})
            continue
        request = queue.begin(item['id'],item['thread'],state['baseline'],api=api)
        prompt = request_text(request)
        with queue.db:
            row=queue.db.execute('SELECT dispatch FROM requests WHERE id=?',(item['id'],)).fetchone()
            dispatch=json.loads(row['dispatch'])
            dispatch.update(transport='cli',prompt=prompt,settings=state['settings'])
            queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
        # No shell, no external text in options. Logs stay private on the laptop.
        folder=queue.state/'cli-runs'
        folder.mkdir(mode=0o700,exist_ok=True)
        output=folder/(str(item['id'])+'.jsonl')
        errors=folder/(str(item['id'])+'.stderr')
        with output.open('x') as stdout, errors.open('x') as stderr:
            result=run(args,input=prompt,text=True,stdout=stdout,stderr=stderr,
                       cwd=state['settings']['cwd'])
        with queue.db:
            dispatch['exit_code']=result.returncode
            queue.db.execute('UPDATE requests SET dispatch=? WHERE id=?',(json.dumps(dispatch),item['id']))
        row=queue.db.execute('SELECT * FROM requests WHERE id=?',(item['id'],)).fetchone()
        matched=collect(queue,home,row)
        return {'status':'completed' if matched else 'needs_reconciliation','id':item['id']}
    unresolved = [row['id'] for row in queue.db.execute(
        "SELECT id FROM requests WHERE status IN ('dispatching','dispatched')")]
    if unresolved:
        return {'status':'needs_reconciliation','ids':unresolved}
    if waiting:
        return {'status':'waiting_for_tasks','requests':waiting}
    return {'status':'idle'}


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=STATE)
    parser.add_argument('--codex',type=Path)
    parser.add_argument('--transport',choices=('cli','shared'),default='cli')
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--interval',type=int,default=10)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if args.transport=='cli' and args.codex is None:
        parser.error('--codex is required for CLI transport')
    if not 1<=args.interval<=300:
        parser.error('interval must be 1..300 seconds')
    home=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))
    previous_result=None
    try:
        while True:
            config=json.loads((args.state/'web.json').read_text())
            if config.get('paused',True):
                return 0
            catalog=json.loads(args.catalog.read_text())
            if catalog.get('project_id') != config['project_id']:
                raise BridgeError('Project mismatch')
            with exclusive(args.state):
                queue=Queue(args.state)
                try:
                    api=API(config)
                    queue.tick(api)
                    if args.transport=='shared':
                        result=asyncio.run(dispatch_shared(queue,home,home/'app-server-control/app-server-control.sock',catalog,api=api))
                    else:
                        result=dispatch_one(queue,home,args.codex,catalog,api=api)
                    queue.tick(api)
                finally:
                    queue.db.close()
            if args.once or (result['status']!='idle' and result!=previous_result):
                print(json.dumps(result),flush=True)
            previous_result=result
            if args.once:
                return 0
            time.sleep(args.interval)
    except (BridgeError,OSError,ValueError,KeyError) as exc:
        print(str(exc) if isinstance(exc,BridgeError) else 'CLI collector error; details hidden',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
