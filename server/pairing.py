"""Short-lived opaque pairing mailbox. Invitation secrets never enter the relay."""
import json
import time
from .opaque import Invalid, Conflict, _binary, validate


def handle(store, action, body, *, collector=False, now=None):
    now = int(time.time() if now is None else now)
    fields = {'register': {'workspace', 'id', 'expires'}, 'offer': {'workspace', 'id', 'public_key', 'envelope'},
              'grant': {'workspace', 'id', 'envelope'}, 'read': {'workspace', 'id'}}
    if (action not in fields or not isinstance(body, dict) or set(body) != fields[action]
            or action in ('register', 'grant') and not collector or action == 'offer' and collector):
        raise Invalid('Invalid pairing operation')
    workspace, ident = body['workspace'], body['id']
    _binary(workspace, 32, 32); _binary(ident, 32, 32)
    if action == 'register' and (type(body['expires']) is not int or not now < body['expires'] <= now + 600):
        raise Invalid('Invalid pairing expiry')
    encoded = None
    if action in ('offer', 'grant'):
        revision = 1 if action == 'offer' else 2
        if validate(body['envelope']) != [workspace, 'devices', 'key-wrap', ident, revision]:
            raise Invalid('Invalid pairing context')
        payload = {'envelope': body['envelope']}
        if action == 'offer':
            _binary(body['public_key'], 256)
            payload['public_key'] = body['public_key']
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        if len(encoded) > (8192 if action == 'offer' else 100000):
            raise Invalid('Pairing payload too large')
    db = store.connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS pairing_mailbox (
          workspace TEXT NOT NULL, id TEXT NOT NULL, expires INTEGER NOT NULL,
          offer TEXT, grant TEXT, PRIMARY KEY(workspace,id))''')
        db.execute('DELETE FROM pairing_mailbox WHERE expires<=?', (now,))
        row = db.execute('SELECT expires,offer,grant FROM pairing_mailbox WHERE workspace=? AND id=?', (workspace, ident)).fetchone()
        result = {'ok': True}
        if action == 'register':
            if row and row[0] != body['expires']:
                raise Conflict('Invitation cannot be changed')
            if not row:
                if db.execute('SELECT count(*) FROM pairing_mailbox').fetchone()[0] >= 32:
                    raise Invalid('Pairing capacity reached')
                db.execute('INSERT INTO pairing_mailbox(workspace,id,expires) VALUES(?,?,?)', (workspace, ident, body['expires']))
        elif row is None:
            raise Invalid('Pairing unavailable or expired')
        elif action == 'read':
            # Browser sees only grant, collector sees only offer; no enumeration API.
            value = row[1 if collector else 2]
            result = {'payload': json.loads(value) if value else None}
        else:
            column, old = ('offer', row[1]) if action == 'offer' else ('grant', row[2])
            if action == 'grant' and row[1] is None:
                raise Invalid('Pairing offer missing')
            if old is not None and old != encoded:
                raise Conflict('Pairing message cannot be replaced')
            db.execute(f'UPDATE pairing_mailbox SET {column}=? WHERE workspace=? AND id=?', (encoded, workspace, ident))
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
