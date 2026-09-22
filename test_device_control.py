import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from device_control import DeviceControl
from device_keys import DeviceKeys,delivery_scope
from device_trust import TrustStore
from key_vault import KeyVault
from sealed_channel import SealedChannel
from test_sealed_channel import Relay
from server.store import Store
from workspace_crypto import Context,CryptoError,decode,encode,public_bytes,seal

class DeviceControlTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        self.vault=KeyVault.create(root/'keys',Relay.url);self.addCleanup(self.vault.db.close)
        self.trust=TrustStore(root/'trust',self.vault.workspace);self.addCleanup(self.trust.db.close)
        self.channel=SealedChannel(Relay(Store(root/'remote')),self.vault)
        self.device=ec.generate_private_key(ec.SECP256R1());public=public_bytes(self.device)
        self.ident=self.trust.trust_device(public)
        self.vault.scope_key('workspace')
        DeviceKeys(self.vault,self.trust,self.channel).configure(self.ident,{'workspace'})
        self.row=self.trust.db.execute('SELECT * FROM devices WHERE id=?',(self.ident,)).fetchone()
        self.control=DeviceControl(self.vault,self.trust,self.channel)

    def entry(self,signer=None,expired=False):
        scope=delivery_scope(public_bytes(self.device));key=self.vault.active_key(scope);now=int(time.time())
        command={'action':'pair-device','issued_at':now-700 if expired else now,'expires_at':now-100 if expired else now+600}
        return {'envelope':seal(decode(key['key'],maximum=32),signer or self.device,
                               Context(self.vault.workspace,scope,'control',encode(secrets.token_bytes(32)),1),json.dumps(command).encode())}

    def test_exact_retry_preserves_one_invitation_and_revocation_stops_control(self):
        entry=self.entry();result=self.control.consume(self.row,entry)
        self.assertEqual(self.control.consume(self.row,entry),result)
        self.assertEqual(self.trust.db.execute('SELECT count(*) FROM pairings').fetchone()[0],1)
        self.trust.revoke_device(self.ident)
        with self.assertRaises(CryptoError):self.control.consume(self.row,entry)

    def test_relay_cannot_forge_owner_or_extend_expiry(self):
        for entry in (self.entry(ec.generate_private_key(ec.SECP256R1())),self.entry(expired=True)):
            with self.assertRaises(CryptoError):self.control.consume(self.row,entry)
        self.assertEqual(self.trust.db.execute('SELECT count(*) FROM pairings').fetchone()[0],0)

    def test_scope_grant_without_owner_catalog_cannot_enroll_devices(self):
        self.vault.scope_key('task')
        DeviceKeys(self.vault,self.trust,self.channel).configure(self.ident,{'task'})
        with self.assertRaises(CryptoError):self.control.consume(self.row,self.entry())
