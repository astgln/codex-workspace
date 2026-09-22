import json
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ec
from device_trust import TrustStore
from key_vault import KeyVault
from pairing_channel import PairingChannel
from server import pairing, opaque
from server.store import Store
from workspace_crypto import Context, decode, encode, public_bytes, seal, open_envelope


class PairingChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.vault=KeyVault.create(root/'keys.db','https://workspace.example');self.addCleanup(self.vault.db.close)
        self.trust=TrustStore(root/'trust.db',self.vault.workspace);self.addCleanup(self.trust.db.close)
        self.store=Store(str(root/'server'))
        self.sent=[]
        test=self
        class API:
            url='https://workspace.example'
            def call(self,path,body):
                test.sent.append(body)
                return pairing.handle(test.store,path.rsplit('/',1)[1],body,collector=True)
        self.channel=PairingChannel(API(),self.vault,self.trust)

    def test_roundtrip_no_secrets_in_relay_and_exact_retry(self):
        invite,link=self.channel.invite()
        self.assertIn('/#pair=',link)
        self.assertNotIn(invite['secret'],json.dumps(self.sent))
        self.assertFalse(self.channel.poll(invite['id'],set()))
        device=ec.generate_private_key(ec.SECP256R1())
        context=Context(invite['workspace'],'devices','key-wrap',invite['id'],1)
        offer=seal(decode(invite['secret'],maximum=32),device,context,b'codex-workspace/device-pairing/v1')
        body={'workspace':invite['workspace'],'id':invite['id'],'public_key':encode(public_bytes(device)),'envelope':offer}
        pairing.handle(self.store,'offer',body)
        self.vault.scope_key('task')
        self.assertTrue(self.channel.poll(invite['id'],{'task'}))
        read={k:invite[k] for k in ('workspace','id')}
        first=pairing.handle(self.store,'read',read)
        self.assertTrue(self.channel.poll(invite['id'],{'task'}))
        self.assertEqual(first,pairing.handle(self.store,'read',read))
        bundle=json.loads(open_envelope(decode(invite['secret'],maximum=32),self.vault.authority.public_key(),
            Context(invite['workspace'],'devices','key-wrap',invite['id'],2),first['payload']['envelope']))
        self.assertEqual([x['scope'] for x in bundle['keys'] if not x['scope'].startswith('device:')],['task'])
        self.assertEqual(sum(x['scope'].startswith('device:') for x in bundle['keys']),1)
        self.assertNotIn(invite['secret'],json.dumps(self.sent))
        changed=dict(body,public_key=encode(public_bytes(ec.generate_private_key(ec.SECP256R1()))))
        with self.assertRaises(opaque.Conflict):pairing.handle(self.store,'offer',changed)
        with self.assertRaises(opaque.Invalid):pairing.handle(self.store,'read',read,now=invite['expires'])

    def test_direction_and_extra_secret_rejected(self):
        invite,_=self.channel.invite()
        body={k:invite[k] for k in ('workspace','id','expires')}
        with self.assertRaises(opaque.Invalid):pairing.handle(self.store,'register',body)
        with self.assertRaises(opaque.Invalid):pairing.handle(self.store,'register',dict(body,secret=invite['secret']),collector=True)
