import tempfile
import unittest
from pathlib import Path
from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.agent.sealed_channel import SealedChannel
from codex_workspace.relay.store import Store
from codex_workspace.relay import opaque
from tests.unit.test_sealed_channel import Relay

class BatchTests(unittest.TestCase):
    def test_uncertain_batch_retries_identical_ciphertext_without_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'server')
            with KeyVault.create(root/'keys',Relay.url) as vault:
                vault.scope_key('task');relay=Relay(store);channel=SealedChannel(relay,vault)
                def send():
                    with channel.batch():
                        for i in range(60):channel.snapshot('task','history',str(i),{'text':'private '+str(i)})
                relay.lose_response=True
                with self.assertRaises(OSError):send()
                first=relay.calls[0][1]['envelopes']
                send()
                self.assertEqual(first,relay.calls[1][1]['envelopes'])
                self.assertLess(len(relay.calls),5)
                db=store.connect()
                self.assertEqual(db.execute('SELECT count(*) FROM opaque_records').fetchone()[0],60);db.close()

    def test_older_journal_cannot_replace_newer_quota(self):
        from codex_workspace.agent.sealed_history import EncryptedHistoryAPI
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root/'server')
            with KeyVault.create(root/'keys',Relay.url) as vault:
                relay=Relay(store);api=EncryptedHistoryAPI(relay,vault)
                fresh={'used_percent':25,'resets_at':5000,'observed_at':2000}
                api.call('/v2/usage',fresh)
                api.call('/v2/usage',dict(fresh,used_percent=10,observed_at=1000))
                self.assertEqual(relay.calls[0][1]['envelope'],relay.calls[1][1]['envelope'])
