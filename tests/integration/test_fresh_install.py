"""Fresh setup and genuine key exchange without private workstation state."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric import ec, utils
from codex_workspace.ops.setup import initialize
from codex_workspace.ops.install_cli_service import definition
from codex_workspace.relay.bootstrap import install_pin, install_mode
from codex_workspace.relay.store import Store
from codex_workspace.relay import pairing, device_auth, sessions
from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.devices.device_trust import TrustStore
from codex_workspace.devices.pairing_channel import PairingChannel
from codex_workspace.devices.auth_registry import snapshot
from codex_workspace.crypto.device_auth import message, sign
from codex_workspace.crypto.workspace_crypto import Context, encode, decode, seal, open_envelope, public_bytes, signer_id
from codex_workspace.agent.workspace_client import API
from codex_workspace.agent.encryption_mode import encrypted_required


class FreshInstallTests(unittest.TestCase):
    def test_new_install_pair_login_and_encrypted_exchange(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'agent';origin='https://fresh.apigw.yandexcloud.net'
            initialize(state,origin,'folder','gateway','main')
            self.assertTrue(encrypted_required(state))
            self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in state.iterdir()))
            config=json.loads((state/'web.json').read_text());api=API(config,state=state)
            deployment=json.loads((state/'deployment.json').read_text())
            self.assertEqual(hashlib.sha256(api.key.encode()).hexdigest(),deployment['client_hash'])
            original=(state/'e2ee-keys.sqlite3').read_bytes()
            with self.assertRaises(FileExistsError):initialize(state,origin,'folder','gateway','main')
            self.assertEqual(original,(state/'e2ee-keys.sqlite3').read_bytes())
            pin=json.loads((state/'device-auth.json').read_text());relay=root/'relay'
            install_pin(relay,pin);install_mode(relay,pin['workspace']);store=Store(relay)
            class LocalTransport:
                url=origin
                def call(self,path,body):return pairing.handle(store,path.rsplit('/',1)[1],body,collector=True)
            with KeyVault(state/'e2ee-keys.sqlite3') as vault, TrustStore(state/'web-queue.sqlite3',vault.workspace) as trust:
                channel=PairingChannel(LocalTransport(),vault,trust)
                invitation,_=channel.invite();device=ec.generate_private_key(ec.SECP256R1())
                secret=decode(invitation['secret'],maximum=32)
                context=Context(vault.workspace,'devices','key-wrap',invitation['id'],1)
                offer=seal(secret,device,context,b'codex-workspace/device-pairing/v1')
                pairing.handle(store,'offer',{'workspace':vault.workspace,'id':invitation['id'],
                    'public_key':encode(public_bytes(device)),'envelope':offer})
                self.assertTrue(channel.poll(invitation['id'],{'workspace'}))
                wrapped=pairing.handle(store,'read',{'workspace':vault.workspace,'id':invitation['id']})
                bundle=json.loads(open_envelope(secret,vault.authority.public_key(),
                    Context(vault.workspace,'devices','key-wrap',invitation['id'],2),wrapped['payload']['envelope']))
                device_auth.registry(store,snapshot(vault,trust),origin)
                ident=signer_id(device);challenge=device_auth.challenge(store,{'device':ident},origin)
                der=decode(sign(device,message('login',origin,vault.workspace,ident,challenge['nonce'],challenge['expires'])),maximum=80)
                a,b=utils.decode_dss_signature(der)
                uid,auth_device=device_auth.authenticate(store,{'device':ident,'nonce':challenge['nonce'],
                    'signature':encode(a.to_bytes(32,'big')+b.to_bytes(32,'big'))},origin)
                token,csrf=sessions.issue(store,uid,auth_device)
                self.assertEqual(sessions.verify(store,token),(uid,csrf))
                key=next(k for k in bundle['keys'] if k['scope']=='workspace')
                context=Context(vault.workspace,'workspace','key-wrap','test',1)
                envelope=seal(decode(key['key'],maximum=32),device,context,b'FRESH INSTALL OK')
                self.assertNotIn('FRESH INSTALL OK',json.dumps(envelope))
                self.assertEqual(open_envelope(decode(vault.active_key('workspace')['key'],maximum=32),device.public_key(),context,envelope),b'FRESH INSTALL OK')
            for kind in ('requests','history'):
                unit=definition(Path('/python'),Path('/codex'),state/'history-catalog.json',state,kind)
                self.assertEqual(unit['Label'],'net.codex-workspace.'+kind)
                self.assertIn(str(state),unit['ProgramArguments'])

    def test_invalid_origin_and_existing_unencrypted_relay_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            state=Path(temp)/'state'
            with self.assertRaises(ValueError):initialize(state,'http://localhost','folder','gateway','main')
            self.assertFalse(state.exists())
            (Path(temp)/'workspace.sqlite3').touch()
            with self.assertRaises(ValueError):install_mode(Path(temp),encode(b'x'*32))
            self.assertFalse((Path(temp)/'e2ee-mode.json').exists())
