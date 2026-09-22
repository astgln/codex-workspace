import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from cryptography.hazmat.primitives.asymmetric import ec
from device_trust import TrustStore
from device_keys import DeviceKeys, delivery_scope
from key_vault import KeyVault
from sealed_channel import SealedChannel
from workspace_crypto import public_bytes, decode, open_envelope, Context

class DeviceKeyTests(unittest.TestCase):
    def test_independent_wraps_and_revoked_device_gets_no_new_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with KeyVault.create(root/'keys','https://workspace.example') as vault, TrustStore(root/'trust',vault.workspace) as trust:
                api=Mock(url=vault.origin)
                delivery=DeviceKeys(vault,trust,SealedChannel(api,vault))
                vault.scope_key('task')
                public=[];ids=[]
                for _ in range(2):
                    key=public_bytes(ec.generate_private_key(ec.SECP256R1()));public.append(key)
                    ids.append(trust.trust_device(key));delivery.configure(ids[-1],{'task'})
                delivery.publish()
                self.assertEqual(api.call.call_count,2)
                first,second=[call.args[1]['envelope'] for call in api.call.call_args_list]
                self.assertNotEqual(first['key_id'],second['key_id'])
                delivery.revoke(ids[0])
                api.reset_mock();delivery.publish()
                self.assertEqual(api.call.call_count,1)
                envelope=api.call.call_args.args[1]['envelope']
                scope=delivery_scope(public[1]);wrap=vault.active_key(scope)
                bundle=json.loads(open_envelope(decode(wrap['key'],maximum=32),vault.authority.public_key(),Context(vault.workspace,scope,'key-wrap','bundle',envelope['context'][4]),envelope))
                self.assertEqual(max(k['epoch'] for k in bundle['keys'] if k['scope']=='task'),2)
                self.assertFalse(any(k['scope']==delivery_scope(public[0]) for k in bundle['keys']))

    def test_interrupted_revocation_resumes_without_repeated_rotation(self):
        from unittest.mock import patch
        from workspace_crypto import CryptoError
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with KeyVault.create(root/'keys','https://workspace.example') as vault, TrustStore(root/'trust',vault.workspace) as trust:
                delivery=DeviceKeys(vault,trust,SealedChannel(Mock(url=vault.origin),vault))
                vault.scope_key('task')
                ident=trust.trust_device(public_bytes(ec.generate_private_key(ec.SECP256R1())))
                delivery.configure(ident,{'task'})
                original=vault.scope_key
                def interrupted(scope,**kwargs):
                    value=original(scope,**kwargs)
                    if kwargs.get('rotate'):raise OSError('simulated crash after rotation')
                    return value
                with patch.object(vault,'scope_key',side_effect=interrupted):
                    with self.assertRaises(OSError):delivery.revoke(ident)
                with self.assertRaises(CryptoError):vault.active_key('task')
                self.assertTrue(delivery.reconcile())
                self.assertEqual(vault.active_key('task')['epoch'],2)
                self.assertFalse(delivery.reconcile())
                self.assertEqual(delivery.publish(),0)
