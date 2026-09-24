import json
import os
from pathlib import Path
import tempfile
import unittest
from codex_workspace.devices.e2ee_admin import backup, write_private, scopes_from_catalog
from codex_workspace.devices.key_vault import KeyVault, read_recovery
from codex_workspace.crypto.workspace_crypto import CryptoError

class AdminTests(unittest.TestCase):
    def test_private_recovery_files_restore_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with KeyVault.create(root/'keys','https://workspace.example') as vault:
                vault.scope_key('task');package=root/'recovery.json';code=root/'recovery.key'
                backup(vault,package,code)
                self.assertEqual(package.stat().st_mode&0o777,0o600)
                self.assertEqual(code.stat().st_mode&0o777,0o600)
                restored=read_recovery(json.loads(package.read_text()),code.read_text().strip(),expected_origin=vault.origin)
                self.assertEqual(restored['workspace'],vault.workspace)
                with self.assertRaises(CryptoError):backup(vault,package,code)
                link=root/'link';link.symlink_to(code)
                with self.assertRaises(FileExistsError):write_private(link,'replacement')
                self.assertTrue(code.read_text().startswith('cw1_'))

    def test_catalog_does_not_choose_internal_key_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog=Path(directory)/'catalog'
            for ident in ['workspace','device:abc','']:
                catalog.write_text(json.dumps({'threads':[{'id':ident}]}))
                with self.assertRaises(CryptoError):scopes_from_catalog(catalog)
            catalog.write_text(json.dumps({'threads':[{'id':'one'},{'id':'two'}]}))
            self.assertEqual(scopes_from_catalog(catalog),{'workspace','one','two'})
