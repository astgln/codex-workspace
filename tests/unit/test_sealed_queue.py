import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric import ec

from codex_workspace.devices.device_trust import ReplayError
from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.agent.runtime_support import BridgeError
from codex_workspace.agent.sealed_queue import SealedQueue
from codex_workspace.crypto.workspace_crypto import Context, CryptoError, decode, encode, public_bytes, seal, signer_id


class SealedQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.vault=KeyVault.create(self.directory/'keys.sqlite3','https://workspace.example')
        self.addCleanup(self.vault.db.close)
        self.current=self.vault.scope_key('task')
        self.queue=SealedQueue(self.directory,self.vault)
        self.addCleanup(self.queue.__exit__,None,None,None)
        self.device=ec.generate_private_key(ec.SECP256R1())
        self.queue.trust.trust_device(public_bytes(self.device))

    def entry(self):
        record=encode(secrets.token_bytes(32))
        context=Context(self.vault.workspace,'task','request',record,1)
        intent={'v':1,'workspace':self.vault.workspace,'thread':'task','request_id':record,
                'issued_at':1000,'expires_at':1600,'text':'test-only-intent','attachments':[]}
        return {'sequence':123,'envelope':seal(decode(self.current['key'],maximum=32),self.device,context,json.dumps(intent).encode())}

    def test_intake_and_nonce_commit_together_and_dispatch_is_durable(self):
        entry=self.entry()
        ident=self.queue.receive('task',entry,now=1001)
        self.assertLess(ident,0)
        self.assertEqual(self.queue.queue.pending()['messages'][0]['text'],'test-only-intent')
        with SealedQueue(self.directory,self.vault) as reopened:
            with self.assertRaises(ReplayError):reopened.receive('task',entry,now=1002)
            result=reopened.begin(ident,'task','baseline',now=1002)
            self.assertEqual(result['text'],'test-only-intent')
            with self.assertRaises(CryptoError):reopened.begin(ident,'task','baseline',now=1003)
        self.assertEqual(self.queue.queue.pending()['messages'][0]['local_status'],'dispatching')

    def test_failed_queue_insert_does_not_consume_nonce(self):
        entry=self.entry()
        def deny(action, table, *_):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_INSERT and table=='requests' else sqlite3.SQLITE_OK
        self.queue.trust.db.set_authorizer(deny)
        with self.assertRaises(sqlite3.DatabaseError):self.queue.receive('task',entry,now=1001)
        self.queue.trust.db.set_authorizer(None)
        self.assertEqual(self.queue.trust.db.execute('SELECT count(*) FROM accepted_requests').fetchone()[0],0)
        self.assertLess(self.queue.receive('task',entry,now=1002),0)

    def test_revocation_and_expiry_rechecked_before_dispatch(self):
        ident=self.queue.receive('task',self.entry(),now=1001)
        with self.assertRaises(CryptoError):self.queue.begin(ident,'task','baseline',now=1600)
        self.queue.trust.revoke_device(signer_id(self.device))
        with self.assertRaises(CryptoError):self.queue.begin(ident,'task','baseline',now=1002)
        self.assertEqual(self.queue.queue.pending()['messages'][0]['local_status'],'pending')

    def test_plaintext_worker_cannot_dispatch_encrypted_request(self):
        ident=self.queue.receive('task',self.entry(),now=1001)
        api=Mock()
        with self.assertRaises(BridgeError):self.queue.queue.begin(ident,'task','baseline',api=api)
        api.call.assert_not_called()

    def test_edited_local_intent_is_not_executed(self):
        ident=self.queue.receive('task',self.entry(),now=1001)
        db=self.queue.trust.db
        payload=json.loads(db.execute('SELECT payload FROM requests WHERE id=?',(ident,)).fetchone()[0])
        payload['text']='substituted'
        db.execute('UPDATE requests SET payload=? WHERE id=?',(json.dumps(payload),ident))
        with self.assertRaises(CryptoError):self.queue.begin(ident,'task','baseline',now=1002)


if __name__=='__main__':unittest.main()
