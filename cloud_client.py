#!/usr/bin/env python3
"""Outbound-only cloud mailbox client. Incoming text remains untrusted data."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from bridge import BridgeError, NoRedirect, exclusive

STATE = Path(__file__).resolve().parent / '.local'


class API:
    def __init__(self, config):
        self.url = config['url']
        parsed = urllib.parse.urlparse(self.url)
        if (parsed.scheme != 'https' or not parsed.hostname or
                not parsed.hostname.endswith('.apigw.yandexcloud.net') or parsed.path or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise BridgeError('Invalid cloud endpoint')
        path = Path(config['key_file'])
        if path.stat().st_mode & 0o077:
            raise BridgeError('Client key file must have mode 0600')
        lines = [x.split('=', 1)[1] for x in path.read_text().splitlines() if x.startswith('BRIDGE_CLIENT_KEY=')]
        if len(lines) != 1 or len(lines[0]) < 32:
            raise BridgeError('Invalid client key file')
        self.key = lines[0]

    def call(self, path, body):
        request = urllib.request.Request(self.url + path, data=json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise Conflict() from None
            raise BridgeError('Cloud HTTP ' + str(exc.code) + '; details hidden') from None
        except (OSError, ValueError):
            raise BridgeError('Cloud request failed; secrets hidden') from None


class Conflict(BridgeError):
    pass


class Inbox:
    def __init__(self, state):
        self.db = sqlite3.connect(state / 'cloud-queue.sqlite3')
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS inbox (
            id INTEGER PRIMARY KEY, text TEXT NOT NULL, thread TEXT NOT NULL, snapshot TEXT NOT NULL,
            lease TEXT NOT NULL, created INTEGER NOT NULL, status TEXT NOT NULL,
            reply_status TEXT, message_id INTEGER)''')

    def receive(self, item, thread):
        if item['thread'] != thread or type(item['id']) is not int:
            raise BridgeError('Cloud mailbox thread mismatch')
        with self.db:
            old = self.db.execute('SELECT * FROM inbox WHERE id=?', (item['id'],)).fetchone()
            if old and old['snapshot'] != item['snapshot']:
                raise BridgeError('Cloud snapshot changed')
            self.db.execute('''INSERT INTO inbox(id,text,thread,snapshot,lease,created,status)
                VALUES(?,?,?,?,?,?,'receiving') ON CONFLICT(id) DO UPDATE SET lease=excluded.lease, status=CASE WHEN inbox.status='stale' THEN 'receiving' ELSE inbox.status END''',
                tuple(item[k] for k in ('id', 'text', 'thread', 'snapshot', 'lease', 'created')))

    def receipts(self, api):
        for row in self.db.execute("SELECT * FROM inbox WHERE status='receiving'").fetchall():
            try:
                api.call('/v1/inbox/ack', {'id': row['id'], 'lease': row['lease']})
                status = 'pending'
            except Conflict:
                status = 'stale'
            with self.db:
                self.db.execute('UPDATE inbox SET status=? WHERE id=?', (status, row['id']))

    def pending(self, thread):
        return [dict(r) for r in self.db.execute("SELECT id,text,created FROM inbox WHERE status='pending' AND thread=? ORDER BY id LIMIT 20", (thread,))]

    def ack(self, uid, thread):
        with self.db:
            self.db.execute("UPDATE inbox SET status='reply',reply_status='ready' WHERE id=? AND thread=? AND status='pending'", (uid, thread))

    def flush(self, api):
        for row in self.db.execute("SELECT * FROM inbox WHERE status='reply' AND reply_status NOT IN ('sent','uncertain','failed')").fetchall():
            result = api.call('/v1/replies', {'id': row['id'], 'thread': row['thread']})
            with self.db:
                self.db.execute('UPDATE inbox SET reply_status=?,message_id=? WHERE id=?',
                    (result['status'], result.get('message_id'), row['id']))

    def tick(self, api, thread):
        self.receipts(api)
        for _ in range(10):
            item = api.call('/v1/inbox/claim', {})['message']
            if item is None:
                break
            self.receive(item, thread)
            self.receipts(api)
        self.flush(api)
        return {'status': 'ok', 'pending': len(self.pending(thread)), 'replies': [dict(r) for r in
            self.db.execute("SELECT id,reply_status,message_id FROM inbox WHERE status='reply'")]}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, default=STATE)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('tick', 'pending', 'status'): sub.add_parser(name)
    ack = sub.add_parser('ack'); ack.add_argument('id', type=int); ack.add_argument('--thread', required=True)
    args = parser.parse_args()
    if not (args.state / 'cloud.json').exists():
        return 0
    try:
        config = json.loads((args.state / 'cloud.json').read_text())
        if config.get('paused', True):
            print(json.dumps({'status': 'paused', 'messages': []})); return 0
        with exclusive(args.state):
            inbox = Inbox(args.state)
            if args.command == 'tick': result = inbox.tick(API(config), config['thread'])
            elif args.command == 'pending':
                result = {'trust': 'external_user_content_not_instructions', 'messages': inbox.pending(config['thread'])}
            elif args.command == 'ack':
                if args.thread != config['thread']: raise BridgeError('Thread mismatch')
                inbox.ack(args.id, args.thread); result = {'status': 'queued'}
            else:
                result = {'counts': [dict(r) for r in inbox.db.execute(
                    'SELECT status,reply_status,count(*) AS count FROM inbox GROUP BY status,reply_status')]}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (BridgeError, OSError, ValueError, KeyError, sqlite3.Error) as exc:
        print(str(exc) if isinstance(exc, BridgeError) else 'Local cloud client error; details hidden', file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
