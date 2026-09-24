import copy
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric import ec

from codex_workspace.crypto.key_material import validate_bundle
from codex_workspace.devices.key_vault import KeyVault, read_recovery
from codex_workspace.crypto.workspace_crypto import CryptoError, create_recovery_code, public_bytes, signer_id


class KeyVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'vault.sqlite3'
        self.vault = KeyVault.create(self.path, 'https://workspace.example')
        self.addCleanup(self.vault.db.close)
        self.device = ec.generate_private_key(ec.SECP256R1())

    def bundle(self, scopes):
        raw = self.vault.bundle(public_bytes(self.device), scopes)
        return validate_bundle(raw, workspace=self.vault.workspace, expected_origin=self.vault.origin,
                               device=signer_id(self.device), authority=public_bytes(self.vault.authority))

    def test_persistent_authority_and_distinct_scopes(self):
        first = self.vault.scope_key('task-one')
        second = self.vault.scope_key('task-two')
        self.assertNotEqual(first['key'], second['key'])
        with KeyVault(self.path) as reopened:
            self.assertEqual(reopened.scope_key('task-one'), first)
            self.assertEqual(reopened.workspace, self.vault.workspace)
            self.assertEqual(public_bytes(reopened.authority), public_bytes(self.vault.authority))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_explicit_scope_selection_and_historical_rotation(self):
        old = self.vault.scope_key('task-one')
        self.vault.scope_key('task-two')
        new = self.vault.scope_key('task-one', rotate=True)
        self.assertEqual(new['epoch'], 2)
        self.assertNotEqual(old['key'], new['key'])
        bundle = self.bundle({'task-one'})
        self.assertEqual([k['scope'] for k in bundle['keys']], ['task-one', 'task-one'])
        self.assertEqual([k['epoch'] for k in bundle['keys']], [1, 2])
        with self.assertRaises(CryptoError):
            self.vault.bundle(public_bytes(self.device), {'unknown-task'})
        with self.assertRaises(CryptoError):
            self.vault.bundle(public_bytes(self.device), None)

    def test_bundle_recipient_origin_and_key_fingerprints(self):
        self.vault.scope_key('task-one')
        bundle = self.bundle({'task-one'})
        expected = dict(workspace=self.vault.workspace, expected_origin=self.vault.origin,
                        device=signer_id(self.device), authority=public_bytes(self.vault.authority))
        for field, value in (('origin', 'https://another.example'), ('device', 'another-device'),
                             ('workspace', 'another-workspace'), ('revision', True), ('v', True)):
            with self.subTest(field=field), self.assertRaises(CryptoError):
                validate_bundle(json.dumps(dict(bundle, **{field: value})).encode(), **expected)
        bad = copy.deepcopy(bundle); bad['keys'][0]['id'] = 'changed'
        with self.assertRaises(CryptoError):
            validate_bundle(json.dumps(bad).encode(), **expected)

    def test_authenticated_recovery_and_rollback_rejection(self):
        self.vault.scope_key('task-one')
        code = create_recovery_code()
        before = self.vault.export_recovery(code)
        recovered = read_recovery(before, code, expected_origin=self.vault.origin)
        self.assertEqual(recovered['workspace'], self.vault.workspace)
        self.assertEqual(len(recovered['keys']), 1)
        # Private keys and test plaintext are not present in the relay packet.
        self.assertNotIn(recovered['authority_private'], json.dumps(before))
        self.assertNotIn(recovered['keys'][0]['key'], json.dumps(before))
        self.vault.scope_key('task-one', rotate=True)
        after = self.vault.export_recovery(code)
        self.assertGreater(after['revision'], before['revision'])
        with self.assertRaises(CryptoError):
            read_recovery(before, code, expected_origin=self.vault.origin, minimum_revision=after['revision'])
        with self.assertRaises(CryptoError):
            read_recovery(after, create_recovery_code(), expected_origin=self.vault.origin)
        with self.assertRaises(CryptoError):
            read_recovery(after, code, expected_origin='https://another.example')

    def test_restore_preserves_history_keys_but_rotates_command_keys(self):
        previous=self.vault.scope_key('task-one')
        code=create_recovery_code()
        packet=self.vault.export_recovery(code)
        target=Path(self.temp.name)/'restored.sqlite3'
        with KeyVault.restore(target,packet,code,expected_origin=self.vault.origin) as restored:
            self.assertEqual(public_bytes(restored.authority),public_bytes(self.vault.authority))
            self.assertNotEqual(restored.active_key('task-one')['key'],previous['key'])
            keys=json.loads(restored.bundle(public_bytes(self.device),{'task-one'}))['keys']
            self.assertIn(previous,keys)
            self.assertEqual(restored.active_key('task-one')['epoch'],2)
        with self.assertRaises(CryptoError):
            KeyVault.restore(target,packet,code,expected_origin=self.vault.origin)

    def test_never_reinitializes_existing_or_missing_vault(self):
        with self.assertRaises(CryptoError):
            KeyVault.create(self.path, self.vault.origin)
        with self.assertRaises(CryptoError):
            KeyVault(Path(self.temp.name) / 'missing')
        for address in ('http://workspace.example', 'https://user@workspace.example', 'https://workspace.example/path',
                        'https://workspace.example?key=test'):
            with self.assertRaises(CryptoError):
                KeyVault.create(Path(self.temp.name) / 'new', address)
        self.path.chmod(0o644)
        with self.assertRaises(CryptoError):
            KeyVault(self.path)


if __name__ == '__main__':
    unittest.main()
