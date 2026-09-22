import json
from unittest.mock import patch
from test_push import PushTests
from key_vault import KeyVault
from sealed_channel import SealedChannel
from sealed_push import publish
from server import encrypted_push
from test_sealed_channel import Relay

class EncryptedPushTests(PushTests):
    def test_relay_sees_only_ciphertext_and_does_not_retry_uncertain(self):
        from pathlib import Path
        self.subscribe()
        with KeyVault.create(Path(self.temp.name)/'keys','https://workspace.example') as vault:
            vault.scope_key('task');channel=SealedChannel(Relay(self.store),vault)
            publish(channel,'task','answer:1','private title','private reply')
            with patch('server.push.send',return_value=None) as send:
                encrypted_push.tick(self.store,'owner',{'workspace':vault.workspace})
                encrypted_push.tick(self.store,'owner',{'workspace':vault.workspace})
                self.assertEqual(send.call_count,1)
                payload=send.call_args.args[2]
                self.assertEqual(set(payload),{'envelope'})
                self.assertNotIn('private',json.dumps(payload))
                self.assertLess(len(json.dumps(payload).encode()),3800)
