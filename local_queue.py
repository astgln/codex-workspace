"""Durable local request states and dispatch identity, independent of CLI entrypoints."""
import hashlib
import json
from pathlib import Path
import sqlite3
from bridge import BridgeError
import queue_downloads
import queue_transport


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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.db.close()

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
        return queue_transport.receipts(self, api)

    def tick(self, api):
        return queue_transport.tick(self, api)

    def downloads(self, api):
        return queue_downloads.downloads(self, api)

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

    def begin(self, ident, thread, baseline, *, api):
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
            decision = api.call('/v2/inbox/validate', {'id': ident, 'thread': thread, 'snapshot': item['snapshot']})
            if not isinstance(decision, dict) or decision.get('allowed') is not True:
                raise BridgeError('Request no longer authorized; dispatch stopped')
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
            # The execution adapter must correlate the exact new Codex turn.
            if not isinstance(body.get('turn_id'), str) or not body['turn_id']:
                raise BridgeError('Missing correlated Codex turn ID')
            if body['turn_id'] == dispatch['baseline']:
                raise BridgeError('A pre-existing Codex turn cannot answer this request')
            if dispatch.get('turn_id',body['turn_id']) != body['turn_id']:
                raise BridgeError('Response moved to another Codex turn')
            dispatch['turn_id']=body['turn_id']
            revision = row['revision'] + 1
            result = {k: body[k] for k in ('thread', 'status', 'events')}
            result.update(id=ident, revision=revision, turn_id=body['turn_id'])
            self.db.execute("UPDATE requests SET status='publishing',result=?,revision=?,dispatch=? WHERE id=?",
                            (json.dumps(result), revision, json.dumps(dispatch), ident))
        return {'status': 'queued', 'revision': revision}

    def status(self):
        return {'counts': [dict(r) for r in self.db.execute('SELECT status,count(*) AS count FROM requests GROUP BY status')]}
