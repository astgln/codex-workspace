import json
import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.fresh_encryption import reset
from workspace_crypto import encode

class FreshEncryptionTests(unittest.TestCase):
    def test_discards_web_content_preserves_identity_and_does_not_reset_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);store=Store(root)
            store.mutate(lambda s:s.update(bindings={'owner':10},catalog={'t':{'id':'t','title':'private title'}}))
            db=store.connect()
            db.execute('CREATE TABLE history_messages(text TEXT)');db.execute("INSERT INTO history_messages VALUES('private transcript')")
            db.commit();db.close()
            for name in ('uploads','migration-backups'):
                (root/name).mkdir();(root/name/'old').write_text('private data')
            workspace=encode(b'x'*32)
            self.assertEqual(reset(root,workspace)['status'],'complete')
            self.assertEqual(store.mutate(lambda s:s['bindings']),{'owner':10})
            self.assertFalse(store.mutate(lambda s:s.get('catalog')))
            self.assertNotIn(b'private transcript',store.path.read_bytes())
            self.assertFalse((root/'uploads').exists());self.assertFalse((root/'migration-backups').exists())
            self.assertEqual((root/'e2ee-mode.json').stat().st_mode&0o777,0o600)
            self.assertEqual(reset(root,workspace)['status'],'already_complete')
            with self.assertRaises(ValueError):reset(root,encode(b'y'*32))
