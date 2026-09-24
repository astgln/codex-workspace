"""Device proof-of-possession login. Public authority pin is installed locally."""
import hashlib
import json
import secrets
import os
import time
from cryptography.exceptions import InvalidSignature
from codex_workspace.crypto.device_auth import key, message, verify
from codex_workspace.crypto.workspace_crypto import signer_id, decode
from codex_workspace.domain.workspace import Unauthorized


def connect(store):
    db = store.connect()
    db.executescript("""
      CREATE TABLE IF NOT EXISTS auth_registry(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, payload TEXT NOT NULL, signature TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS device_challenges(id TEXT PRIMARY KEY, device TEXT NOT NULL, expires INTEGER NOT NULL);
    """)
    return db


def pin(store):
    path = store.directory / 'device-auth.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_size > 2048:
        raise ValueError('Authentication authority not configured')
    value = json.loads(path.read_text())
    if set(value) != {'workspace', 'authority'}: raise ValueError('Invalid authority pin')
    decode(value['workspace'], maximum=32, exact=32)
    key(value['authority'])
    return value


def registry(store, body, origin, *, now=None):
    now = int(time.time() if now is None else now)
    authority = pin(store)
    if not isinstance(body, dict) or set(body) != {'payload', 'signature'}: raise ValueError('Invalid registry')
    p = body['payload']
    if not isinstance(p, dict) or set(p) != {'v','workspace','origin','owner','devices','issued','expires','revision'}:
        raise ValueError('Invalid registry')
    verify(key(authority['authority']), body['signature'], message('registry', p))
    if (p['v'] != 1 or p['workspace'] != authority['workspace'] or p['origin'] != origin or
        type(p['owner']) is not int or not 0 < p['owner'] < 2**53 or
        any(type(p[x]) is not int for x in ('issued','expires','revision')) or
        not 0 < p['revision'] < 2**53 or p['issued'] > now + 60 or not now < p['expires'] <= p['issued'] + 86400 or
        not isinstance(p['devices'], list) or len(p['devices']) > 1000): raise ValueError('Invalid registry')
    seen = set()
    for d in p['devices']:
        if (not isinstance(d, dict) or set(d) != {'id','public_key','uid'} or type(d['uid']) is not int or
            not 0 < d['uid'] < 2**53 or d['id'] in seen or signer_id(key(d['public_key'])) != d['id']):
            raise ValueError('Invalid device identity')
        if d['uid'] != p['owner']:raise ValueError('Single-user registry required')
        seen.add(d['id'])
    value = json.dumps(p, separators=(',', ':'))
    db = connect(store)
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT revision,payload FROM auth_registry WHERE id=1').fetchone()
        if row and (row[0] > p['revision'] or row[0] == p['revision'] and row[1] != value): raise ValueError('Registry rollback')
        db.execute('INSERT OR REPLACE INTO auth_registry VALUES(1,?,?,?)', (p['revision'], value, body['signature']))
        db.commit()
    finally: db.close()
    store.mutate(lambda state: state['bindings'].update({os.environ.get('OWNER_USERNAME','owner'):p['owner']}))
    return {'ok': True}


def current(store, *, now=None):
    now = int(time.time() if now is None else now)
    authority = pin(store)
    db = connect(store)
    try: row = db.execute('SELECT payload,signature FROM auth_registry WHERE id=1').fetchone()
    finally: db.close()
    if not row: raise Unauthorized()
    value = json.loads(row[0])
    try:verify(key(authority['authority']),row[1],message('registry',value))
    except (InvalidSignature,ValueError,TypeError):raise Unauthorized() from None
    if value['expires'] <= now or value['workspace'] != authority['workspace']: raise Unauthorized()
    return value


def identity(store, device):
    value = current(store)
    for d in value['devices']:
        if d['id'] == device: return d, value
    raise Unauthorized()


def challenge(store, body, origin):
    if not isinstance(body, dict) or set(body) != {'device'}: raise ValueError('Invalid login request')
    decode(body['device'], maximum=32, exact=32)
    # Unknown and revoked keys get the same response shape. Verification decides.
    authority = pin(store)
    now = int(time.time()); nonce = secrets.token_urlsafe(32); expires = now + 60
    db = connect(store)
    try:
        with db:
            db.execute('DELETE FROM device_challenges WHERE expires<=?', (now,))
            if db.execute('SELECT count(*) FROM device_challenges').fetchone()[0] >= 256: raise ValueError('Login capacity reached')
            db.execute('INSERT INTO device_challenges VALUES(?,?,?)', (nonce, body['device'], expires))
    finally: db.close()
    return {'nonce': nonce, 'expires': expires, 'workspace': authority['workspace'], 'origin': origin}


def authenticate(store, body, origin):
    if not isinstance(body, dict) or set(body) != {'nonce','device','signature'}: raise Unauthorized()
    decode(body['nonce'], maximum=32, exact=32)
    d, value = identity(store, body['device'])
    db = connect(store)
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT device,expires FROM device_challenges WHERE id=?', (body['nonce'],)).fetchone()
        if not row or row[0] != d['id'] or row[1] <= time.time(): raise Unauthorized()
        try: verify(key(d['public_key']), body['signature'], message('login', origin, value['workspace'], d['id'], body['nonce'], row[1]), browser=True)
        except (InvalidSignature, ValueError, TypeError): raise Unauthorized() from None
        db.execute('DELETE FROM device_challenges WHERE id=?', (body['nonce'],)); db.commit()
    finally: db.close()
    return d['uid'], d['id']
