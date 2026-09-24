"""Publish only locally authorized public device identities, signed by authority."""
import json
import time
from codex_workspace.crypto.device_auth import message, sign
from codex_workspace.crypto.workspace_crypto import encode


def identities(trust):
    from codex_workspace.crypto.workspace_crypto import CryptoError
    row=trust.db.execute('SELECT value FROM encrypted_access WHERE id=1').fetchone()
    if not row:raise CryptoError('Local account registry is not initialized')
    state=json.loads(row['value']);owner=state['bindings']['owner'];mapping={}
    for row in trust.db.execute("""SELECT devices.id,device_grants.scopes,encrypted_device_members.uid
          FROM devices JOIN device_grants ON devices.id=device_grants.device LEFT JOIN encrypted_device_members
          ON devices.id=encrypted_device_members.device WHERE devices.revoked=0"""):
        scopes=json.loads(row['scopes'])
        if row['uid'] is None:
            if 'workspace' in scopes:mapping[row['id']]=owner
        elif row['uid'] in state['bindings'].values() and row['uid']!=owner and 'workspace' not in scopes:
            mapping[row['id']]=row['uid']
    return owner,mapping


def _snapshot(vault, trust, *, now=None):
    now = int(time.time() if now is None else now)
    owner, mapping = identities(trust)
    devices = [{'id': row['id'], 'public_key': encode(row['public_key']), 'uid': mapping[row['id']]}
               for row in trust.db.execute('SELECT * FROM devices WHERE revoked=0 ORDER BY id') if row['id'] in mapping]
    payload = {'v': 1, 'workspace': vault.workspace, 'origin': vault.origin, 'owner': owner, 'devices': devices,
               'issued': now, 'expires': now + 86400}
    # Monotone per-authority revision, persisted before transport and safe on retry.
    db = trust.db
    db.execute('CREATE TABLE IF NOT EXISTS auth_registry_outbox(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, payload TEXT, signature TEXT)')
    row = db.execute('SELECT * FROM auth_registry_outbox WHERE id=1').fetchone()
    if row:
        previous = json.loads(row['payload'])
        if previous['devices'] == devices and previous['owner'] == owner and now - previous['issued'] < 60:
            return {'payload': previous, 'signature': row['signature']}
    payload['revision'] = max(now*1000,row['revision']+1 if row else 1)
    signature = sign(vault.authority, message('registry', payload))
    db.execute('INSERT OR REPLACE INTO auth_registry_outbox VALUES(1,?,?,?)',
               (payload['revision'], json.dumps(payload, separators=(',', ':')), signature))
    return {'payload': payload, 'signature': signature}


def publish(api, vault, trust):
    api.call('/v2/e2ee/auth/registry', snapshot(vault, trust))


def snapshot(vault,trust,*,now=None):
    trust.db.execute('BEGIN IMMEDIATE')
    try:
        result=_snapshot(vault,trust,now=now)
        trust.db.execute('COMMIT')
        return result
    except BaseException:
        trust.db.execute('ROLLBACK');raise
