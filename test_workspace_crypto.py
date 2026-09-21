"""Endpoint crypto tests; these keys are generated for each test, never installed."""
import copy
import unittest
from dataclasses import replace

from cryptography.hazmat.primitives.asymmetric import ec

from workspace_crypto import (Context, CryptoError, MAX_PLAINTEXT, create_recovery_code,
                              decode, encode, open_envelope, recovery_key, seal)


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes(range(32))
        self.signing = ec.generate_private_key(ec.SECP256R1())
        self.context = Context('test-workspace', 'test-task', 'request', 'random-client-request-id', 1)
        self.plaintext = 'Проверка, а не пользовательские данные 🔐'.encode()
        self.envelope = seal(self.key, self.signing, self.context, self.plaintext)

    def open(self, envelope=None, context=None, key=None, signer=None):
        return open_envelope(key or self.key, signer or self.signing.public_key(),
                             context or self.context, envelope or self.envelope)

    def test_roundtrip_and_independent_randomness(self):
        other = seal(self.key, self.signing, self.context, self.plaintext)
        self.assertEqual(self.open(), self.plaintext)
        self.assertEqual(self.open(other), self.plaintext)
        for field in ('nonce', 'salt', 'ciphertext'):
            self.assertNotEqual(other[field], self.envelope[field])

    def test_routing_context_cannot_be_substituted(self):
        for field, value in (('workspace', 'different'), ('scope', 'another-task'), ('kind', 'response'),
                             ('record', 'replayed-under-new-id'), ('revision', 2)):
            with self.subTest(field=field), self.assertRaises(CryptoError):
                self.open(context=replace(self.context, **{field: value}))

    def test_routing_context_rewrite_breaks_signature(self):
        changed = copy.deepcopy(self.envelope)
        changed['context'][1] = 'another-task'
        with self.assertRaises(CryptoError):
            self.open(changed, context=replace(self.context, scope='another-task'))

    def test_tampering_each_binary_field_fails(self):
        for field in ('salt', 'nonce', 'ciphertext', 'signature'):
            changed = copy.deepcopy(self.envelope)
            raw = bytearray(decode(changed[field], maximum=MAX_PLAINTEXT + 16))
            raw[0] ^= 1
            changed[field] = encode(raw)
            with self.subTest(field=field), self.assertRaises(CryptoError):
                self.open(changed)

    def test_shared_encryption_key_does_not_grant_author_identity(self):
        impostor = ec.generate_private_key(ec.SECP256R1())
        forged = seal(self.key, impostor, self.context, self.plaintext)
        with self.assertRaises(CryptoError):
            self.open(forged)
        forged['signer'] = self.envelope['signer']
        with self.assertRaises(CryptoError):
            self.open(forged)

    def test_wrong_encryption_key_fails(self):
        with self.assertRaises(CryptoError):
            self.open(key=b'x' * 32)

    def test_rejects_ambiguous_or_unversioned_envelopes(self):
        cases = [dict(self.envelope, v=True), dict(self.envelope, v=2), dict(self.envelope, text='plaintext'),
                 dict(self.envelope, signature=''), dict(self.envelope, nonce=self.envelope['nonce'] + '='),
                 dict(self.envelope, context=[*self.envelope['context'][:4], True]),
                 dict(self.envelope, context=tuple(self.envelope['context'])),
                 dict(self.envelope, ciphertext='a' * ((MAX_PLAINTEXT + 17) * 2))]
        for case in cases:
            with self.assertRaises(CryptoError):
                self.open(case)
        for value in ('plaintext', None, [], {}, {'v': 1}):
            with self.assertRaises(CryptoError):
                open_envelope(self.key, self.signing.public_key(), self.context, value)

    def test_empty_and_binary_contents_supported(self):
        for content in (b'', bytes(range(256))):
            self.assertEqual(self.open(seal(self.key, self.signing, self.context, content)), content)

    def test_invalid_context_and_size_fail(self):
        for context in (replace(self.context, revision=0), replace(self.context, revision=True),
                        replace(self.context, revision=2**53), replace(self.context, scope=''),
                        replace(self.context, kind='unknown'), replace(self.context, record='x' * 513),
                        replace(self.context, record='\ud800')):
            with self.assertRaises(CryptoError):
                seal(self.key, self.signing, context, b'test')
        with self.assertRaises(CryptoError):
            seal(self.key, self.signing, self.context, b'x' * (MAX_PLAINTEXT + 1))

    def test_recovery_randomness_checksum_and_domain(self):
        first, second = create_recovery_code(), create_recovery_code()
        self.assertNotEqual(first, second)
        self.assertEqual(len(recovery_key(first)), 32)
        self.assertNotEqual(recovery_key(first), decode(first[4:], maximum=36)[:32])
        changed = bytearray(decode(first[4:], maximum=36)); changed[1] ^= 1
        for value in ('', 'password', first + '=', 'cw1_' + encode(changed)):
            with self.assertRaises(CryptoError):
                recovery_key(value)


if __name__ == '__main__':
    unittest.main()
