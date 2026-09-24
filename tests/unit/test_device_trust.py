import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest

from cryptography.hazmat.primitives.asymmetric import ec

from codex_workspace.devices.device_trust import PAIRING_PROOF, ReplayError, TrustStore
from codex_workspace.crypto.workspace_crypto import Context, CryptoError, decode, encode, open_envelope, public_bytes, seal, signer_id


class DeviceTrustTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'devices.sqlite3'
        self.store = TrustStore(self.path, 'test-workspace')
        self.addCleanup(self.store.db.close)
        self.authority = ec.generate_private_key(ec.SECP256R1())
        self.device = ec.generate_private_key(ec.SECP256R1())
        self.key = secrets.token_bytes(32)

    def request(self, *, scope='task', record=None, device=None):
        context = Context('test-workspace', scope, 'request', record or encode(secrets.token_bytes(32)), 1)
        now = int(time.time())
        payload = {'v': 1, 'workspace': context.workspace, 'thread': context.scope, 'request_id': context.record,
                   'issued_at': now, 'expires_at': now + 600, 'text': 'test-only-request', 'attachments': []}
        return context, seal(self.key, device or self.device, context, json.dumps(payload).encode())

    def offer(self, invite, device=None):
        device = device or self.device
        return seal(decode(invite['secret'], maximum=32), device,
                    Context('test-workspace', 'devices', 'key-wrap', invite['id'], 1), PAIRING_PROOF)

    def pair(self, invite, offer=None, device=None, now=100):
        device = device or self.device
        return self.store.pair(invite['id'], public_bytes(device), offer or self.offer(invite, device),
                               self.authority, self.bundle(device), expected_origin='https://workspace.example', now=now)

    def bundle(self, device):
        return json.dumps({'v':1,'workspace':'test-workspace','origin':'https://workspace.example',
            'device':signer_id(device),'authority':encode(public_bytes(self.authority)),'revision':1,'keys':[]}, separators=(',',':')).encode()

    def test_untrusted_device_and_revocation_fail_closed(self):
        context, request = self.request()
        with self.assertRaises(CryptoError):
            self.store.accept_request(self.key, context, request)
        ident = self.store.trust_device(public_bytes(self.device))
        self.store.revoke_device(ident)
        with self.assertRaises(CryptoError):
            self.store.accept_request(self.key, context, request)
        with self.assertRaises(CryptoError):
            self.store.trust_device(public_bytes(self.device))

    def test_durable_replay_detection_survives_reconnect_and_routing_changes(self):
        self.store.trust_device(public_bytes(self.device))
        context, request = self.request()
        self.assertEqual(self.store.accept_request(self.key, context, request)['text'], 'test-only-request')
        with TrustStore(self.path, 'test-workspace') as second:
            with self.assertRaises(ReplayError):
                second.accept_request(self.key, context, request)
            # A legitimately re-signed request cannot reuse a consumed nonce in another task.
            other_context, other = self.request(scope='other-task', record=context.record)
            with self.assertRaises(ReplayError):
                second.accept_request(self.key, other_context, other)

    def test_failed_verification_does_not_consume_request(self):
        self.store.trust_device(public_bytes(self.device))
        context, request = self.request()
        with self.assertRaises(CryptoError):
            self.store.accept_request(b'x' * 32, context, request)
        self.assertEqual(self.store.accept_request(self.key, context, request)['text'], 'test-only-request')

    def test_pairing_round_trip_and_exact_retry(self):
        invite = self.store.invite(public_bytes(self.authority), now=100)
        offer = self.offer(invite)
        response = self.pair(invite, offer)
        self.assertEqual(self.pair(invite, offer, now=101), response)
        plaintext = open_envelope(decode(invite['secret'], maximum=32), self.authority.public_key(),
                                 Context('test-workspace', 'devices', 'key-wrap', invite['id'], 2), response)
        self.assertEqual(plaintext, self.bundle(self.device))
        context, request = self.request()
        self.assertEqual(self.store.accept_request(self.key, context, request)['text'], 'test-only-request')
        self.assertIsNone(self.store.db.execute('SELECT secret FROM pairings').fetchone()[0])

    def test_second_device_cannot_reuse_invitation(self):
        invite = self.store.invite(public_bytes(self.authority), now=100)
        self.pair(invite)
        another = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(ReplayError):
            self.pair(invite, device=another)

    def test_pairing_authority_must_match_out_of_band_pin(self):
        invite = self.store.invite(public_bytes(self.authority), now=100)
        wrong = ec.generate_private_key(ec.SECP256R1())
        with self.assertRaises(CryptoError):
            self.store.pair(invite['id'], public_bytes(self.device), self.offer(invite), wrong, b'keys', expected_origin='https://workspace.example', now=100)
        self.pair(invite)

    def test_expired_or_tampered_invitation_cannot_enroll(self):
        invite = self.store.invite(public_bytes(self.authority), now=100)
        with self.assertRaises(CryptoError):
            self.pair(invite, now=700)
        fresh = self.store.invite(public_bytes(self.authority), now=1000)
        wrong = dict(fresh, secret=encode(secrets.token_bytes(32)))
        with self.assertRaises(CryptoError):
            self.pair(fresh, self.offer(wrong), now=1001)
        context, request = self.request()
        with self.assertRaises(CryptoError):
            self.store.accept_request(self.key, context, request)

    def test_revoked_key_cannot_pair_or_retrieve_pairing_again(self):
        invite = self.store.invite(public_bytes(self.authority), now=100)
        offer = self.offer(invite)
        self.pair(invite, offer)
        self.store.revoke_device(signer_id(self.device))
        with self.assertRaises(CryptoError):
            self.pair(invite, offer)
        fresh = self.store.invite(public_bytes(self.authority), now=200)
        with self.assertRaises(CryptoError):
            self.pair(fresh, now=201)

    def test_private_permissions_and_workspace_binding(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(CryptoError):
            TrustStore(self.path, 'different-workspace')
        link = Path(self.temp.name) / 'link.sqlite3'
        link.symlink_to(self.path)
        with self.assertRaises(CryptoError):
            TrustStore(link, 'test-workspace')
        self.path.chmod(0o644)
        with self.assertRaises(CryptoError):
            TrustStore(self.path, 'test-workspace')


if __name__ == '__main__':
    unittest.main()
