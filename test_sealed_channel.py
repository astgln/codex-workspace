import json
from pathlib import Path
import secrets
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric import ec

from device_trust import ReplayError, TrustStore
from key_vault import KeyVault
from sealed_channel import SealedChannel
from server import opaque
from server.store import Store
from workspace_crypto import Context, CryptoError, decode, encode, open_envelope, public_bytes, seal


class Relay:
    url = 'https://workspace.example'

    def __init__(self, store):
        self.store, self.calls, self.lose_response = store, [], False

    def call(self, route, body):
        self.calls.append((route, json.loads(json.dumps(body))))
        if route in ('/v2/e2ee/publish','/v2/e2ee/publish-batch'):
            response = opaque.publish_batch(self.store,body) if route.endswith('publish-batch') else opaque.publish(self.store, body)
            if self.lose_response:
                self.lose_response = False
                raise OSError('Simulated lost acknowledgement')
            return response
        if route == '/v2/e2ee/read':
            return opaque.read(self.store, body)
        raise AssertionError('Plaintext transport is forbidden')


class SealedChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.vault = KeyVault.create(directory / 'keys.sqlite3', Relay.url)
        self.addCleanup(self.vault.db.close)
        self.trust = TrustStore(directory / 'trust.sqlite3', self.vault.workspace)
        self.addCleanup(self.trust.db.close)
        self.remote = Store(directory / 'remote')
        self.api = Relay(self.remote)
        self.channel = SealedChannel(self.api, self.vault)
        self.current = self.vault.scope_key('task')
        self.device = ec.generate_private_key(ec.SECP256R1())
        self.trust.trust_device(public_bytes(self.device))

    def submit(self, *, signing=None, text='test-intent'):
        context = Context(self.vault.workspace, 'task', 'request', encode(secrets.token_bytes(32)), 1)
        intent = {'v':1,'workspace':context.workspace,'thread':'task','request_id':context.record,
                  'issued_at':1000,'expires_at':1600,'text':text,'attachments':[]}
        envelope = seal(decode(self.current['key'], maximum=32), signing or self.device,
                        context, json.dumps(intent).encode())
        opaque.publish(self.remote, {'envelope':envelope}, browser=True)
        return intent

    def test_authenticated_encrypted_roundtrip_without_plaintext_relay(self):
        intent = self.submit()
        entry = self.channel.requests('task', 0)['records'][0]
        accepted = self.channel.accept(self.trust, 'task', entry, now=1001)
        self.assertEqual(accepted, intent)
        self.channel.publish('task', 'response', intent['request_id'], 1, {'text':'test-answer'})
        result = opaque.read(self.remote, {'workspace':self.vault.workspace,'scope':'task','kind':'response','after':0}, browser=True)
        response = result['records'][0]['envelope']
        plaintext = open_envelope(decode(self.current['key'],maximum=32), self.vault.authority.public_key(),
                                  Context(self.vault.workspace,'task','response',intent['request_id'],1), response)
        self.assertEqual(json.loads(plaintext), {'text':'test-answer'})
        for _, body in self.api.calls:
            self.assertNotIn('test-intent', json.dumps(body))
            self.assertNotIn('test-answer', json.dumps(body))
        with self.assertRaises(ReplayError):
            self.channel.accept(self.trust, 'task', entry, now=1002)

    def test_uncertain_publication_reuses_persisted_ciphertext(self):
        self.api.lose_response = True
        with self.assertRaises(OSError):
            self.channel.publish('task','history','message',1,{'text':'test-text'})
        replay = SealedChannel(self.api, self.vault).publish('task','history','message',1,{'text':'test-text'})
        self.assertTrue(replay['duplicate'])
        self.assertEqual(self.api.calls[0][1], self.api.calls[1][1])
        with self.assertRaises(CryptoError):
            self.channel.publish('task','history','message',1,{'text':'changed'})

    def test_unknown_signer_expiry_and_rotated_request_key_fail_closed(self):
        self.submit(signing=ec.generate_private_key(ec.SECP256R1()))
        entry = self.channel.requests('task',0)['records'][0]
        with self.assertRaises(CryptoError):
            self.channel.accept(self.trust,'task',entry,now=1001)
        self.submit()
        entry = self.channel.requests('task',entry['sequence'])['records'][0]
        with self.assertRaises(CryptoError):
            self.channel.accept(self.trust,'task',entry,now=1600)
        self.vault.scope_key('task',rotate=True)
        with self.assertRaises(CryptoError):
            self.channel.accept(self.trust,'task',entry,now=1001)

    def test_wrong_origin_or_unconfigured_scope_never_uses_network(self):
        bad = Relay(self.remote); bad.url='https://different.example'
        with self.assertRaises(CryptoError):
            SealedChannel(bad,self.vault)
        with self.assertRaises(CryptoError):
            self.channel.requests('unconfigured',0)
        with self.assertRaises(CryptoError):
            self.channel.publish('unconfigured','catalog','task',1,{'title':'test'})
        self.assertEqual(self.api.calls,[])


if __name__ == '__main__':
    unittest.main()
