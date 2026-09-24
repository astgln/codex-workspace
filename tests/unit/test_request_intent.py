import json
import unittest

from codex_workspace.agent.request_intent import validate_request
from codex_workspace.crypto.workspace_crypto import Context, CryptoError, encode


class RequestIntentTests(unittest.TestCase):
    def setUp(self):
        self.context = Context('workspace', 'task', 'request', encode(b'n' * 32), 1)
        self.value = {'v': 1, 'workspace': 'workspace', 'thread': 'task', 'request_id': self.context.record,
                      'issued_at': 1000, 'expires_at': 1600, 'text': 'test-only-request', 'attachments': []}

    def test_valid_intent(self):
        self.assertEqual(validate_request(json.dumps(self.value).encode(), self.context, 1001), self.value)

    def test_signed_but_stale_future_or_mismatched_intent_rejected(self):
        for updates in ({'expires_at': 1001}, {'issued_at': 1062}, {'issued_at': True}, {'v': True},
                        {'expires_at': 1000 + 86401}, {'thread': 'other-task'}, {'workspace': 'other-workspace'},
                        {'request_id': encode(b'm' * 32)}, {'text': ''}, {'text': '\ud800'},
                        {'extra_untrusted_field': 'value'}):
            with self.subTest(updates=updates), self.assertRaises(CryptoError):
                validate_request(json.dumps(dict(self.value, **updates)).encode(), self.context, 1001)

    def test_duplicate_json_keys_rejected(self):
        raw = json.dumps(self.value).replace('"v": 1', '"v": 2, "v": 1').encode()
        with self.assertRaises(CryptoError):
            validate_request(raw, self.context, 1001)

    def test_file_context_hash_and_local_name_constraints(self):
        attachment = {'id': encode(b'f' * 32), 'name': 'log.txt', 'size': 123,
                      'sha256': 'a' * 64, 'ciphertext_sha256': 'b' * 64}
        value = dict(self.value, attachments=[attachment])
        self.assertEqual(validate_request(json.dumps(value).encode(), self.context, 1001), value)
        for updates in ({'name': '../log.txt'}, {'name': '..\\log.txt'}, {'name': '\ud800'}, {'size': True},
                        {'sha256': 'bad'}, {'ciphertext_sha256': ''}, {'id': ''}):
            with self.subTest(updates=updates), self.assertRaises(CryptoError):
                changed = dict(self.value, attachments=[dict(attachment, **updates)])
                validate_request(json.dumps(changed).encode(), self.context, 1001)
        with self.assertRaises(CryptoError):
            validate_request(json.dumps(dict(value, attachments=[attachment, attachment])).encode(), self.context, 1001)


if __name__ == '__main__':
    unittest.main()
