"""Signed owner-device management. Relay identities never authorize enrollment."""
import hashlib
import json
import time
from codex_workspace.devices.device_keys import delivery_scope
from codex_workspace.crypto.key_material import public_key
from codex_workspace.devices.pairing_channel import PairingChannel
from codex_workspace.crypto.workspace_crypto import Context, CryptoError, decode, encode, open_envelope, public_bytes


class DeviceControl:
    def __init__(self,vault,trust,channel,catalog=None):
        self.catalog=catalog
        self.vault,self.trust,self.channel=vault,trust,channel
        trust.db.execute('''CREATE TABLE IF NOT EXISTS device_controls (
          record TEXT PRIMARY KEY, signer TEXT NOT NULL, digest TEXT NOT NULL, result TEXT NOT NULL, paired INTEGER NOT NULL DEFAULT 0)''')
        trust.db.execute('CREATE TABLE IF NOT EXISTS control_cursors (device TEXT PRIMARY KEY,position INTEGER NOT NULL)')

    def consume(self,device,entry):
        envelope=entry['envelope'];record=envelope['context'][3]
        decode(record,maximum=32,exact=32)
        scope=delivery_scope(device['public_key'])
        digest=hashlib.sha256(json.dumps(envelope,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        db=self.trust.db;db.execute('BEGIN IMMEDIATE')
        try:
            owner=db.execute('''SELECT devices.revoked,device_grants.scopes FROM devices JOIN device_grants
                              ON devices.id=device_grants.device WHERE devices.id=?''',(device['id'],)).fetchone()
            if not owner or owner['revoked'] or 'workspace' not in json.loads(owner['scopes']):
                raise CryptoError('Local owner enrollment required')
            cached=db.execute('SELECT * FROM device_controls WHERE record=?',(record,)).fetchone()
            if cached:
                if cached['signer']!=device['id'] or cached['digest']!=digest:raise CryptoError('Control replay changed')
                result=json.loads(cached['result'])
            else:
                key=self.vault.active_key(scope)
                raw=open_envelope(decode(key['key'],maximum=32),public_key(encode(device['public_key'])),
                                  Context(self.vault.workspace,scope,'control',record,1),envelope)
                command=json.loads(raw)
                now=int(time.time())
                if (not isinstance(command,dict) or set(command) not in ({'action','issued_at','expires_at'},{'action','issued_at','expires_at','args'})
                        or command['action'] not in ('pair-device','list-devices','grants','member-policy','decide')
                        or type(command['issued_at']) is not int or type(command['expires_at']) is not int
                        or command['issued_at']>now+60 or command['expires_at']<=now
                        or not 0<command['expires_at']-command['issued_at']<=600):
                    raise CryptoError('Invalid device control intent')
                if command['action'] in ('grants','member-policy','decide'):
                    if not self.catalog or not isinstance(command.get('args'),dict):raise CryptoError('Missing signed policy arguments')
                    from codex_workspace.devices.sealed_access import LocalAccess
                    policy=LocalAccess(self.vault,self.trust)
                    if command['action']=='decide':policy.decision(device['id'],command['args'],self.catalog,envelope)
                    else:policy.prepare(device['id'],command['action'],command['args'],self.catalog)
                    result={'ok':True}
                elif command['action']=='pair-device':
                    args=command.get('args',{})
                    if not isinstance(args,dict) or set(args) not in (set(),{'user_id'}):raise CryptoError('Invalid enrollment arguments')
                    target=args.get('user_id')
                    if target is not None:
                        if not self.catalog:raise CryptoError('Local catalog unavailable')
                        from codex_workspace.devices.sealed_access import LocalAccess
                        state=LocalAccess(self.vault,self.trust).state(self.catalog)
                        if type(target) is not int or target not in state['bindings'].values() or target==state['bindings']['owner']:raise CryptoError('Unknown local member')
                    result={'invitation':self.trust.invite(public_bytes(self.vault.authority)),**({'member_uid':target} if target is not None else {})}
                else:
                    result={'devices':[{'id':r['id'],'revoked':bool(r['revoked'])} for r in db.execute('SELECT id,revoked FROM devices')]}
                db.execute('INSERT INTO device_controls(record,signer,digest,result) VALUES(?,?,?,?)',
                           (record,device['id'],digest,json.dumps(result,separators=(',',':'))))
            db.execute('COMMIT');return result
        except BaseException:
            db.execute('ROLLBACK');raise

    def tick(self,scopes):
        db=self.trust.db
        devices=db.execute('''SELECT devices.*,device_grants.scopes FROM devices JOIN device_grants
                             ON devices.id=device_grants.device WHERE devices.revoked=0''').fetchall()
        for device in devices:
            if 'workspace' not in json.loads(device['scopes']):continue
            cursor=db.execute('SELECT position FROM control_cursors WHERE device=?',(device['id'],)).fetchone()
            scope=delivery_scope(device['public_key'])
            for entry in self.channel.requests(scope,cursor[0] if cursor else 0,kind='control')['records']:
                try:
                    result=self.consume(device,entry)
                except CryptoError:
                    # Invalid/expired signed controls cannot block later requests.
                    # No grant or invitation is issued for a rejected envelope.
                    db.execute('INSERT INTO control_cursors VALUES(?,?) ON CONFLICT(device) DO UPDATE SET position=excluded.position',
                               (device['id'],entry['sequence']))
                    continue
                if self.catalog:
                    from codex_workspace.devices.sealed_access import LocalAccess
                    LocalAccess(self.vault,self.trust).reconcile()
                invitation=result.get('invitation')
                if invitation:
                    self.channel.api.call('/v2/e2ee/pairing/register',{k:invitation[k] for k in ('workspace','id','expires')})
                self.channel.publish(scope,'control-result',entry['envelope']['context'][3],1,result)
                db.execute('INSERT INTO control_cursors VALUES(?,?) ON CONFLICT(device) DO UPDATE SET position=excluded.position',
                           (device['id'],entry['sequence']))
        pairing=PairingChannel(self.channel.api,self.vault,self.trust)
        for row in db.execute('SELECT record,signer,result FROM device_controls WHERE paired=0').fetchall():
            invitation=json.loads(row['result']).get('invitation')
            if not invitation:continue
            issuer=db.execute('SELECT devices.revoked,device_grants.scopes FROM devices JOIN device_grants ON devices.id=device_grants.device WHERE devices.id=?',(row['signer'],)).fetchone()
            if not issuer or issuer['revoked'] or 'workspace' not in json.loads(issuer['scopes']):
                db.execute('DELETE FROM pairings WHERE id=?',(invitation['id'],));continue
            if invitation['expires']<=int(time.time()):continue
            target=json.loads(row['result']).get('member_uid')
            grants=set(scopes)|{'workspace'}
            if target is not None:
                from codex_workspace.domain import access
                from codex_workspace.devices.sealed_access import LocalAccess
                grants=set(access.permitted_threads(LocalAccess(self.vault,self.trust).state(self.catalog),target,'owner'))
            if pairing.poll(invitation['id'],grants,member_uid=target):
                db.execute('UPDATE device_controls SET paired=1 WHERE record=?',(row['record'],))
