import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from codex_workspace.devices.device_control import DeviceControl
from codex_workspace.devices.device_keys import DeviceKeys, delivery_scope
from codex_workspace.devices.device_trust import TrustStore
from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.agent.sealed_channel import SealedChannel
from tests.unit.test_sealed_channel import Relay
from codex_workspace.relay.store import Store
from codex_workspace.crypto.workspace_crypto import Context, CryptoError, decode, encode, public_bytes, seal

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

    def test_expired_control_does_not_block_fresh_invitation(self):
        from unittest.mock import patch
        entries=[dict(self.entry(expired=True),sequence=1),dict(self.entry(),sequence=2)]
        original=self.channel.api.call
        def relay(route,body):
            if route=='/v2/e2ee/pairing/register':return {'ok':True}
            if route=='/v2/e2ee/pairing/read':return {'payload':None}
            return original(route,body)
        with patch.object(self.channel,'requests',return_value={'records':entries}),patch.object(self.channel.api,'call',side_effect=relay):
            self.control.tick({'workspace'})
        self.assertEqual(self.trust.db.execute('SELECT position FROM control_cursors').fetchone()[0],2)
        self.assertEqual(self.trust.db.execute('SELECT count(*) FROM device_controls').fetchone()[0],1)
        self.assertEqual(self.trust.db.execute('SELECT count(*) FROM pairings').fetchone()[0],1)
