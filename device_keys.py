"""Per-device key delivery, authorized solely by the endpoint's local registry."""
import json
from key_material import public_key
from workspace_crypto import CryptoError, encode, signer_id


def delivery_scope(public):
    return 'device:' + signer_id(public_key(encode(public)))


class DeviceKeys:
    def __init__(self, vault, trust, channel):
        if vault.workspace != trust.workspace:
            raise CryptoError('Device registry workspace mismatch')
        self.vault, self.trust, self.channel = vault, trust, channel
        vault.db.execute('CREATE TABLE IF NOT EXISTS key_transition (id INTEGER PRIMARY KEY CHECK(id=1), reason TEXT NOT NULL)')
        trust.db.execute('''CREATE TABLE IF NOT EXISTS device_grants (
          device TEXT PRIMARY KEY, scopes TEXT NOT NULL)''')

    def configure(self, ident, scopes):
        if not isinstance(scopes, set) or any(not isinstance(s,str) or s.startswith('device:') for s in scopes):
            raise CryptoError('Invalid local device scopes')
        self.vault.assert_ready()
        row=self.trust.db.execute('SELECT public_key,revoked FROM devices WHERE id=?',(ident,)).fetchone()
        if row is None or row['revoked']:
            raise CryptoError('Device is not trusted')
        for scope in scopes:self.vault.active_key(scope)
        self.vault.scope_key(delivery_scope(row['public_key']))
        encoded=json.dumps(sorted(scopes),separators=(',',':'))
        old=self.trust.db.execute('SELECT scopes FROM device_grants WHERE device=?',(ident,)).fetchone()
        if old and old['scopes']==encoded:return
        removed = set(json.loads(old['scopes'])) - scopes if old else set()
        self._transition({'device':ident,'scopes':sorted(scopes),'revoke':False,
                          'rotate':{scope:self.vault.active_key(scope)['epoch']+1 for scope in removed}})

    def revoke(self, ident):
        self.vault.assert_ready()
        device=self.trust.db.execute('SELECT revoked FROM devices WHERE id=?',(ident,)).fetchone()
        if device is None:raise CryptoError('Unknown local device')
        if device['revoked']:return
        row=self.trust.db.execute('SELECT scopes FROM device_grants WHERE device=?',(ident,)).fetchone()
        scopes=json.loads(row['scopes']) if row else []
        self._transition({'device':ident,'scopes':[], 'revoke':True,
                          'rotate':{scope:self.vault.active_key(scope)['epoch']+1 for scope in scopes}})

    def _transition(self, plan):
        # Persist the full plan before changing either database. After a crash,
        # resume only this local plan; the relay never supplies recovery choices.
        self.vault.db.execute('INSERT INTO key_transition VALUES(1,?)',(json.dumps(plan,sort_keys=True),))
        self.reconcile()

    def reconcile(self):
        row=self.vault.db.execute('SELECT reason FROM key_transition WHERE id=1').fetchone()
        if row is None:return False
        try:plan=json.loads(row['reason'])
        except (TypeError,ValueError):raise CryptoError('Invalid local key transition') from None
        if (not isinstance(plan,dict) or set(plan)!={'device','scopes','revoke','rotate'}
                or not isinstance(plan['device'],str) or not isinstance(plan['scopes'],list)
                or type(plan['revoke']) is not bool or not isinstance(plan['rotate'],dict)):
            raise CryptoError('Invalid local key transition')
        device=self.trust.db.execute('SELECT id FROM devices WHERE id=?',(plan['device'],)).fetchone()
        if device is None:raise CryptoError('Transition device is unavailable')
        # Remove access before rotation. A blocked transition cannot export keys.
        self.trust.db.execute('INSERT INTO device_grants VALUES(?,?) ON CONFLICT(device) DO UPDATE SET scopes=excluded.scopes',
                              (plan['device'],json.dumps(plan['scopes'],separators=(',',':'))))
        if plan['revoke']:self.trust.revoke_device(plan['device'])
        for scope,target in plan['rotate'].items():
            if type(target) is not int or target<2:raise CryptoError('Invalid transition epoch')
            key=self.vault.scope_key(scope)
            if key['epoch']<target:
                if key['epoch']!=target-1:raise CryptoError('Transition epoch mismatch')
                self.vault.scope_key(scope,rotate=True)
        self.vault.db.execute('BEGIN IMMEDIATE')
        try:
            self.vault.db.execute('UPDATE identity SET revision=revision+1 WHERE id=1')
            self.vault.db.execute('DELETE FROM key_transition')
            self.vault.db.execute('COMMIT')
        except BaseException:
            self.vault.db.execute('ROLLBACK');raise
        return True

    def sync_owner_scopes(self, scopes):
        """Single-account catalog updates; only locally enrolled owner devices.

        Possession of the workspace catalog grant is established by local pairing,
        never by an identity or permissions object supplied by the web relay.
        """
        if any(not isinstance(scope,str) or scope=='workspace' or scope.startswith('device:') for scope in scopes):
            raise CryptoError('Reserved catalog scope')
        scopes=set(scopes)|{'workspace'}
        for scope in scopes:self.vault.scope_key(scope)
        owners=self.trust.db.execute("""SELECT devices.id,device_grants.scopes FROM devices
          JOIN device_grants ON devices.id=device_grants.device WHERE devices.revoked=0""").fetchall()
        for owner in owners:
            if 'workspace' in json.loads(owner['scopes']):self.configure(owner['id'],scopes)

    def publish(self):
        # Serialize entitlement reads with local grant/revocation writes. Without
        # this lock, a removed scope could be read before rotation and its new key
        # bundled after rotation for a device that just lost access.
        self.trust.db.execute('BEGIN IMMEDIATE')
        try:
            rows=self.trust.db.execute("""SELECT devices.id,devices.public_key,device_grants.scopes
              FROM devices JOIN device_grants ON devices.id=device_grants.device WHERE devices.revoked=0""").fetchall()
            for row in rows:
                scope=delivery_scope(row['public_key'])
                bundle=json.loads(self.vault.bundle(row['public_key'],set(json.loads(row['scopes']))|{scope}))
                self.channel.publish(scope,'key-wrap','bundle',bundle['revision'],bundle)
            self.trust.db.execute('COMMIT')
            return len(rows)
        except BaseException:
            self.trust.db.execute('ROLLBACK');raise
