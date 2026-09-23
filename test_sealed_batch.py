import tempfile
import unittest
from pathlib import Path
from key_vault import KeyVault
from sealed_channel import SealedChannel
from server.store import Store
from server import opaque
from test_sealed_channel import Relay

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
