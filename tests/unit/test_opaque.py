import json
from pathlib import Path
import secrets
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric import ec

from codex_workspace.relay import opaque
from codex_workspace.relay.store import Store
from codex_workspace.crypto.workspace_crypto import Context, encode, open_envelope, seal


class OpaqueRelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.key = secrets.token_bytes(32)
        self.signing = ec.generate_private_key(ec.SECP256R1())

    def envelope(self, *, kind='history', record='record', revision=1, text=b'sensitive-test-content'):
        context = Context('workspace', 'task', kind, record, revision)
        return seal(self.key, self.signing, context, text)

    def read(self, **changes):
        body = {'workspace': 'workspace', 'scope': 'task', 'kind': 'history', 'after': 0}
        return opaque.read(self.store, dict(body, **changes), browser=True)

    def test_server_roundtrip_is_ciphertext_only(self):
        envelope = self.envelope()
        result = opaque.publish(self.store, {'envelope': envelope})
        self.assertEqual(result, {'sequence': 1, 'duplicate': False})
        records = self.read()['records']
        self.assertEqual(records[0]['envelope'], envelope)
        decrypted = open_envelope(self.key, self.signing.public_key(), Context(*envelope['context']), records[0]['envelope'])
        self.assertEqual(decrypted, b'sensitive-test-content')
        db = self.store.connect()
        try:
            dump = '\n'.join(db.iterdump())
        finally:
            db.close()
        self.assertNotIn('sensitive-test-content', dump)
        self.assertNotIn(encode(self.key), dump)

    def test_monotonic_revisions_and_exact_retries(self):
        first = self.envelope()
        opaque.publish(self.store, {'envelope': first})
        self.assertTrue(opaque.publish(self.store, {'envelope': first})['duplicate'])
        with self.assertRaises(opaque.Conflict):
            opaque.publish(self.store, {'envelope': self.envelope()})
        updated = self.envelope(revision=2)
        opaque.publish(self.store, {'envelope': updated})
        with self.assertRaises(opaque.Conflict):
            opaque.publish(self.store, {'envelope': first})
        self.assertEqual(self.read(after=1)['records'][0]['envelope'], updated)

    def test_requests_are_immutable_and_direction_separated(self):
        request = self.envelope(kind='request', record=encode(secrets.token_bytes(32)))
        with self.assertRaises(opaque.Invalid):
            opaque.publish(self.store, {'envelope': request})
        opaque.publish(self.store, {'envelope': request}, browser=True)
        with self.assertRaises(opaque.Invalid):
            opaque.publish(self.store, {'envelope': self.envelope()}, browser=True)
        changed = self.envelope(kind='request', record=request['context'][3], revision=2)
        with self.assertRaises(opaque.Invalid):
            opaque.publish(self.store, {'envelope': changed}, browser=True)

    def test_no_plaintext_extension_downgrade_or_oversized_record(self):
        envelope = self.envelope()
        for body in ({'text': 'plaintext'}, {'envelope': envelope, 'text': 'plaintext'},
                     {'envelope': dict(envelope, text='plaintext')}, {'envelope': dict(envelope, v=True)},
                     {'envelope': self.envelope(text=b'x' * (opaque.MAX_CIPHERTEXT + 1))}):
            with self.assertRaises(opaque.Invalid):
                opaque.publish(self.store, body)
        self.assertEqual(self.read()['records'], [])

    def test_pagination_and_scope_isolation(self):
        for index in range(52):
            opaque.publish(self.store, {'envelope': self.envelope(record=str(index))})
        first = self.read()
        second = self.read(after=first['after'])
        self.assertEqual(len(first['records']), 50)
        self.assertTrue(first['more'])
        self.assertEqual(len(second['records']), 2)
        self.assertFalse(second['more'])
        self.assertEqual(self.read(scope='another-task')['records'], [])


if __name__ == '__main__':
    unittest.main()

    def test_parallel_polling_and_history_publication(self):
        from concurrent.futures import ThreadPoolExecutor
        envelopes=[self.envelope(record='parallel:'+str(i)) for i in range(40)]
        def work(i):
            opaque.publish(self.store,{'envelope':envelopes[i]})
            return self.read()
        with ThreadPoolExecutor(max_workers=4) as pool:
            for result in pool.map(work,range(40)):self.assertIsInstance(result['records'],list)
        self.assertEqual(len(self.read()['records']),40)
