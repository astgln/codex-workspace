import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric import ec

from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.agent.sealed_attachments import download, install
from codex_workspace.agent.sealed_queue import SealedQueue
from codex_workspace.crypto.workspace_crypto import public_bytes
from codex_workspace.relay import opaque_files
from codex_workspace.relay.opaque import Conflict, Invalid
from codex_workspace.relay.store import Store
from codex_workspace.crypto.workspace_crypto import Context, CryptoError, decode, encode, seal


class FileAPI:
    url='https://workspace.example'
    def __init__(self,store):self.store=store
    def call(self,path,body):
        if not path.startswith('/v2/e2ee/files/'):raise AssertionError('Plaintext file path forbidden')
        return opaque_files.handle(self.store,None,path.rsplit('/',1)[1],body,collector=True)


class SealedAttachmentsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.vault=KeyVault.create(self.root/'keys.sqlite3',FileAPI.url);self.addCleanup(self.vault.db.close)
        self.scope_key=self.vault.scope_key('task')
        self.store=Store(self.root/'relay');self.api=FileAPI(self.store)
        self.device=ec.generate_private_key(ec.SECP256R1())
        self.identity={'workspace':self.vault.workspace,'scope':'task','id':encode(secrets.token_bytes(32))}
        self.plaintext=b'secret-test-log-content\n'*5000
        envelope=seal(decode(self.scope_key['key'],maximum=32),self.device,
                      Context(self.vault.workspace,'task','attachment',self.identity['id'],1),self.plaintext)
        self.encrypted=json.dumps(envelope,separators=(',',':')).encode()
        self.manifest={'id':self.identity['id'],'name':'private-test-name.log','size':len(self.plaintext),
                       'sha256':hashlib.sha256(self.plaintext).hexdigest(),
                       'ciphertext_sha256':hashlib.sha256(self.encrypted).hexdigest()}

    def start(self):
        return opaque_files.handle(self.store,42,'start',{**self.identity,'size':len(self.encrypted),
                                                        'sha256':self.manifest['ciphertext_sha256']})

    def upload(self):
        self.start()
        for offset in range(0,len(self.encrypted),opaque_files.CHUNK):
            opaque_files.handle(self.store,42,'chunk',{**self.identity,'index':offset//opaque_files.CHUNK,
                                                       'data':encode(self.encrypted[offset:offset+opaque_files.CHUNK])})
        opaque_files.handle(self.store,42,'finish',self.identity)

    def test_ciphertext_store_to_verified_local_file(self):
        self.upload()
        # Historical file epochs can still be read after request key rotation.
        self.vault.scope_key('task',rotate=True)
        content=download(self.api,self.vault,'task',self.manifest,self.device.public_key())
        self.assertEqual(content,self.plaintext)
        target=self.root/'downloads';target.mkdir(mode=0o700)
        saved=install(target,self.manifest,content)
        self.assertEqual(Path(saved['path']).read_bytes(),self.plaintext)
        self.assertEqual(Path(saved['path']).stat().st_mode&0o777,0o600)
        self.assertEqual(install(target,self.manifest,content),saved)
        db=self.store.connect()
        try:dump='\n'.join(db.iterdump())
        finally:db.close()
        self.assertNotIn(self.manifest['name'],dump)
        self.assertNotIn(self.manifest['sha256'],dump)
        for path in (self.store.directory/'encrypted-uploads').rglob('*'):
            if path.is_file():self.assertNotIn(b'secret-test-log-content',path.read_bytes())

    def test_missing_changed_and_unauthorized_chunks_rejected(self):
        self.start()
        with self.assertRaises(Invalid):opaque_files.handle(self.store,42,'finish',self.identity)
        self.upload()
        with self.assertRaises(Invalid):opaque_files.handle(self.store,99,'describe',self.identity)
        changed=encode(b'x'*opaque_files.CHUNK)
        with self.assertRaises(Conflict):
            opaque_files.handle(self.store,42,'chunk',{**self.identity,'index':0,'data':changed})
        with self.assertRaises(Invalid):
            opaque_files.handle(self.store,None,'start',self.identity,collector=True)

    def test_substitution_and_wrong_signer_never_yield_plaintext(self):
        self.upload()
        with self.assertRaises(CryptoError):
            download(self.api,self.vault,'task',dict(self.manifest,ciphertext_sha256='a'*64),self.device.public_key())
        with self.assertRaises(CryptoError):
            download(self.api,self.vault,'task',self.manifest,ec.generate_private_key(ec.SECP256R1()).public_key())
        with self.assertRaises(CryptoError):
            download(self.api,self.vault,'task',dict(self.manifest,sha256='b'*64),self.device.public_key())

    def test_attachment_must_be_verified_before_queue_dispatch(self):
        self.upload()
        with SealedQueue(self.root,self.vault) as queue:
            queue.trust.trust_device(public_bytes(self.device))
            request_id=encode(secrets.token_bytes(32))
            context=Context(self.vault.workspace,'task','request',request_id,1)
            intent={'v':1,'workspace':self.vault.workspace,'thread':'task','request_id':request_id,
                    'issued_at':1000,'expires_at':1600,'text':'inspect attached test log','attachments':[self.manifest]}
            envelope=seal(decode(self.scope_key['key'],maximum=32),self.device,context,json.dumps(intent).encode())
            ident=queue.receive('task',{'envelope':envelope},now=1001)
            with self.assertRaises(CryptoError):queue.begin(ident,'task','baseline',now=1002)
            files=queue.download_files(self.api,ident,now=1002)
            path=Path(files[0]['path'])
            path.write_bytes(b'changed')
            with self.assertRaises(CryptoError):queue.begin(ident,'task','baseline',now=1003)
            path.write_bytes(self.plaintext)
            result=queue.begin(ident,'task','baseline',now=1003)
            self.assertEqual(result['files'],files)

    def test_plaintext_metadata_and_path_traversal_rejected(self):
        with self.assertRaises(Invalid):
            opaque_files.handle(self.store,42,'start',{**self.identity,'size':len(self.encrypted),
                                                       'sha256':self.manifest['ciphertext_sha256'],'name':'private-name'})
        target=self.root/'downloads';target.mkdir(mode=0o700)
        with self.assertRaises(CryptoError):install(target,dict(self.manifest,name='../escape'),self.plaintext)
        (target/self.manifest['id']).symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(CryptoError):install(target,self.manifest,self.plaintext)


if __name__=='__main__':unittest.main()
