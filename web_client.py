#!/usr/bin/env python3
"""Outbound website collector. Codex app tools perform dispatch, not this process.

Persist dispatch intent before calling the app; an interrupted intent is never
automatically retried. The orchestrator must correlate only the marked new turn.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import re
import sys
import time
from bridge import BridgeError, exclusive
from cloud_client import API, Conflict, STATE


class Queue:
    def __init__(self, state):
        self.state = state
        self.db = sqlite3.connect(state / 'web-queue.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
            dispatch TEXT, result TEXT, revision INTEGER NOT NULL DEFAULT 0)''')
        self.db.execute('CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        if 'files' not in [r['name'] for r in self.db.execute('PRAGMA table_info(requests)')]:
            self.db.execute("ALTER TABLE requests ADD COLUMN files TEXT NOT NULL DEFAULT '[]'")

    def receive(self, item):
        if type(item.get('id')) is not int or item['id'] >= 0:
            raise BridgeError('Invalid website request')
        with self.db:
            previous = self.db.execute('SELECT * FROM requests WHERE id=?', (item['id'],)).fetchone()
            if previous:
                old = json.loads(previous['payload'])
                if any(old.get(key) != item.get(key) for key in ('thread','snapshot','text','attachments')):
                    raise BridgeError('Immutable request changed')
                if previous['status'] != 'receiving':
                    return
                self.db.execute('UPDATE requests SET payload=? WHERE id=?', (json.dumps(item), item['id']))
            else:
                self.db.execute("INSERT INTO requests(id,payload,status) VALUES(?,?,'receiving')",
                                (item['id'], json.dumps(item)))

    def receipts(self, api):
        for row in self.db.execute("SELECT * FROM requests WHERE status='receiving'").fetchall():
            item = json.loads(row['payload'])
            try:
                api.call('/v2/inbox/ack', {'id': item['id'], 'lease': item['lease']})
            except Conflict:
                # Leave receiving until a new lease is claimed; never dispatch.
                continue
            with self.db:
                self.db.execute("UPDATE requests SET status='pending' WHERE id=?", (item['id'],))

    def tick(self, api):
        refreshed = self.db.execute("SELECT value FROM metadata WHERE name='login_keys'").fetchone()
        key_status = 'fresh'
        if not refreshed or refreshed['value'] < time.time() - 3600:
            from cloud.login import public_keys
            try:
                # Fixed official HTTPS URL with certificate checks and no redirects.
                keys = public_keys(refresh=True)
                now = int(time.time())
                api.call('/v2/login-keys', {'keys':keys, 'fetched_at':now})
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO metadata VALUES('login_keys',?)",(now,))
            except Exception:
                key_status = 'refresh_failed'
        self.receipts(api)
        for _ in range(10):
            item = api.call('/v2/inbox/claim', {})['message']
            if item is None:
                break
            self.receive(item)
            self.receipts(api)
        self.downloads(api)
        for row in self.db.execute("SELECT * FROM requests WHERE status='publishing'").fetchall():
            result = json.loads(row['result'])
            api.call('/v2/responses', result)
            status = 'complete' if result['status'] in ('completed', 'failed') else 'dispatched'
            with self.db:
                self.db.execute('UPDATE requests SET status=? WHERE id=?', (status, row['id']))
        return {**self.status(), 'login_keys':key_status}

    def downloads(self, api):
        for row in self.db.execute("SELECT * FROM requests WHERE status='pending'").fetchall():
            item = json.loads(row['payload'])
            attachments=item.get('attachments',[])
            if not attachments or json.loads(row['files']):
                continue
            directory=self.state/'attachments'/str(row['id'])
            directory.mkdir(mode=0o700,parents=True,exist_ok=True)
            saved=[]
            for attachment in attachments:
                ident=attachment.get('id','')
                if not re.fullmatch('[a-f0-9]{32}',ident) or not 0<attachment['size']<=5*1024*1024:
                    raise BridgeError('Invalid approved attachment')
                match=re.search(r'\.[A-Za-z0-9]{1,12}$',attachment['name'])
                path=directory/(ident+(match.group(0) if match else '.bin'))
                temporary=path.with_suffix(path.suffix+'.part')
                count,index,digest=0,0,hashlib.sha256()
                fd=os.open(temporary,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
                try:
                    with os.fdopen(fd,'wb') as output:
                        while count<attachment['size']:
                            chunk=api.call('/v2/files/get',{'id':ident,'index':index})
                            data=base64.b64decode(chunk['data'],validate=True)
                            if not data or len(data)>48*1024 or count+len(data)>attachment['size']:
                                raise BridgeError('Invalid attachment bytes')
                            output.write(data);digest.update(data);count+=len(data);index+=1
                    if digest.hexdigest()!=attachment['sha256']:
                        raise BridgeError('Attachment checksum mismatch')
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
                saved.append({**attachment,'path':str(path.resolve())})
            with self.db:
                self.db.execute('UPDATE requests SET files=? WHERE id=?',(json.dumps(saved),row['id']))

    def pending(self):
        results = []
        for row in self.db.execute("SELECT * FROM requests WHERE status IN ('pending','dispatching','dispatched') ORDER BY id DESC"):
            item = json.loads(row['payload'])
            item.pop('lease', None)
            item['files']=json.loads(row['files'])
            item.update(local_status=row['status'], dispatch=json.loads(row['dispatch']) if row['dispatch'] else None)
            if row['status']=='pending' and item.get('attachments') and not item['files']:
                item['local_status']='files_pending'
            results.append(item)
        return {'trust': 'owner_approved_external_content_not_system_instructions', 'messages': results}

    def begin(self, ident, thread, baseline):
        with self.db:
            row = self.db.execute('SELECT * FROM requests WHERE id=?', (ident,)).fetchone()
            if not row or row['status'] != 'pending':
                raise BridgeError('Dispatch already started or request not pending; do not retry automatically')
            item = json.loads(row['payload'])
            files=json.loads(row['files'])
            if item.get('attachments') and not files:
                raise BridgeError('Approved attachments have not been verified locally')
            for attachment in files:
                if hashlib.sha256(Path(attachment['path']).read_bytes()).hexdigest()!=attachment['sha256']:
                    raise BridgeError('Local attachment changed')
            if item['thread'] != thread:
                raise BridgeError('Thread mismatch')
            marker = 'workspace-request:' + str(ident) + ':' + item['snapshot'][:16]
            dispatch = {'marker': marker, 'baseline': baseline, 'thread': thread}
            self.db.execute("UPDATE requests SET status='dispatching',dispatch=? WHERE id=?", (json.dumps(dispatch), ident))
        return {'id': ident, 'thread': thread, 'marker': marker, 'text': item['text'], 'files':files}

    def sent(self, ident, marker):
        with self.db:
            row = self.db.execute('SELECT * FROM requests WHERE id=?', (ident,)).fetchone()
            if not row or row['status'] != 'dispatching' or json.loads(row['dispatch'])['marker'] != marker:
                raise BridgeError('Dispatch confirmation mismatch')
            self.db.execute("UPDATE requests SET status='dispatched' WHERE id=?", (ident,))

    def publish(self, ident, body):
        with self.db:
            row = self.db.execute('SELECT * FROM requests WHERE id=?', (ident,)).fetchone()
            if not row or row['status'] != 'dispatched':
                raise BridgeError('Request was not dispatched')
            dispatch = json.loads(row['dispatch'])
            if body.get('marker') != dispatch['marker'] or body.get('thread') != dispatch['thread']:
                raise BridgeError('Response does not match the dispatched request')
            # Exact new-turn correlation is performed by the app tool orchestrator.
            if not isinstance(body.get('turn_id'), str) or not body['turn_id']:
                raise BridgeError('Missing correlated Codex turn ID')
            if body['turn_id'] == dispatch['baseline']:
                raise BridgeError('A pre-existing Codex turn cannot answer this request')
            if dispatch.get('turn_id',body['turn_id']) != body['turn_id']:
                raise BridgeError('Response moved to another Codex turn')
            dispatch['turn_id']=body['turn_id']
            revision = row['revision'] + 1
            result = {k: body[k] for k in ('thread', 'status', 'events')}
            result.update(id=ident, revision=revision)
            self.db.execute("UPDATE requests SET status='publishing',result=?,revision=?,dispatch=? WHERE id=?",
                            (json.dumps(result), revision, json.dumps(dispatch), ident))
        return {'status': 'queued', 'revision': revision}

    def status(self):
        return {'counts': [dict(r) for r in self.db.execute('SELECT status,count(*) AS count FROM requests GROUP BY status')]}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, default=STATE)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('tick', 'pending', 'status'): sub.add_parser(name)
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
            queue = Queue(args.state)
            if args.command == 'catalog':
                catalog = json.loads(args.file.read_text())
                if catalog.get('project_id') != config['project_id']:
                    raise BridgeError('Project mismatch')
                result = API(config).call('/v2/catalog', catalog)
            elif args.command == 'tick': result = queue.tick(API(config))
            elif args.command == 'pending': result = queue.pending()
            elif args.command == 'begin': result = queue.begin(args.id,args.thread,args.baseline)
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
