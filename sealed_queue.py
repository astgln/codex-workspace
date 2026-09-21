"""Atomic encrypted intake. Durable queue state shares the local trust database."""
import hashlib
import json
import time

from local_queue import Queue
from device_trust import TrustStore
from request_intent import validate_request
from workspace_crypto import Context, CryptoError, decode, encode, open_envelope
from key_material import public_key


class SealedQueue:
    def __init__(self, directory, vault):
        self.queue = Queue(directory)
        try:
            self.trust = TrustStore(directory / 'web-queue.sqlite3', vault.workspace)
        except BaseException:
            self.queue.db.close()
            raise
        self.vault = vault

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.trust.db.close()
        self.queue.db.close()

    def receive(self, scope, entry, *, now=None):
        envelope = entry.get('envelope') if isinstance(entry, dict) else None
        if not isinstance(envelope, dict) or not isinstance(envelope.get('context'), list) or len(envelope['context']) != 5:
            raise CryptoError('Invalid encrypted queue entry')
        expected = Context(self.vault.workspace, scope, 'request', envelope['context'][3], 1)
        current = self.vault.active_key(scope)
        local_id = None

        def persist(db, request):
            nonlocal local_id
            # Relay sequence/IDs do not choose or alias a local execution record.
            local_id = min(db.execute('SELECT coalesce(min(id),0) FROM requests').fetchone()[0],0)-1
            canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            payload = {'id':local_id,'thread':request['thread'],'text':request['text'],
                       'request_id':request['request_id'],'created':request['issued_at'],
                       'expires':request['expires_at'],'attachments':request['attachments'],
                       'snapshot':hashlib.sha256(canonical.encode()).hexdigest(),'encrypted_envelope':envelope}
            db.execute("INSERT INTO requests(id,payload,status) VALUES(?,?,'pending')",
                       (local_id,json.dumps(payload,ensure_ascii=False)))

        self.trust.accept_request(decode(current['key'],maximum=32), expected, envelope, now=now, persist=persist)
        return local_id

    def begin(self, ident, thread, baseline, *, now=None):
        """Local cryptographic authorization and dispatch intent commit together.

        CLI/task permission checks still belong to the existing execution layer.
        Attachments must pass signature/hash checks and be installed locally first.
        """
        db = self.trust.db
        db.execute('BEGIN IMMEDIATE')
        try:
            row = db.execute('SELECT * FROM requests WHERE id=?',(ident,)).fetchone()
            if row is None or row['status'] != 'pending':
                raise CryptoError('Encrypted dispatch already started or unavailable')
            item = json.loads(row['payload'])
            request,_=self._verify_item(db,item,thread,now)
            files=json.loads(row['files'])
            by_id={file.get('id'):file for file in files if isinstance(file,dict)}
            if len(files)!=len(request['attachments']) or len(by_id)!=len(files):
                raise CryptoError('Encrypted attachments are not verified locally')
            from pathlib import Path
            for manifest in request['attachments']:
                file=by_id.get(manifest['id'])
                if (file is None or file.get('sha256')!=manifest['sha256'] or file.get('name')!=manifest['name']):
                    raise CryptoError('Encrypted attachment manifest changed')
                path=Path(file['path'])
                if path.is_symlink() or not path.is_file() or path.stat().st_size!=manifest['size']:
                    raise CryptoError('Local encrypted attachment changed')
                if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['sha256']:
                    raise CryptoError('Local encrypted attachment changed')
            marker = 'workspace-request:' + str(ident) + ':' + item['snapshot'][:16]
            dispatch = {'marker':marker,'baseline':baseline,'thread':thread}
            db.execute("UPDATE requests SET status='dispatching',dispatch=? WHERE id=?",(json.dumps(dispatch),ident))
            db.execute('COMMIT')
            return {'id':ident,'thread':thread,'marker':marker,'text':request['text'],'files':files}
        except BaseException:
            db.execute('ROLLBACK')
            raise

    def _verify_item(self,db,item,thread,now):
        envelope = item.get('encrypted_envelope')
        if not isinstance(envelope,dict):
            raise CryptoError('Plaintext requests cannot use encrypted dispatch')
        signer = db.execute('SELECT public_key,revoked FROM devices WHERE id=?',(envelope.get('signer'),)).fetchone()
        if signer is None or signer['revoked']:
            raise CryptoError('Untrusted device')
        current = self.vault.active_key(thread)
        expected = Context(self.vault.workspace,thread,'request',item.get('request_id'),1)
        signer_key=public_key(encode(signer['public_key']))
        plaintext = open_envelope(decode(current['key'],maximum=32),signer_key,expected,envelope)
        request = validate_request(plaintext,expected,int(time.time() if now is None else now))
        canonical = json.dumps(request,sort_keys=True,ensure_ascii=False,separators=(',',':'))
        if (item['thread'] != thread or item['text'] != request['text'] or item['attachments'] != request['attachments']
                or item['snapshot'] != hashlib.sha256(canonical.encode()).hexdigest()):
            raise CryptoError('Encrypted queue intent changed')
        return request,signer_key

    def download_files(self,api,ident,*,now=None):
        from sealed_attachments import download,install
        db=self.trust.db
        row=db.execute('SELECT * FROM requests WHERE id=?',(ident,)).fetchone()
        if row is None or row['status']!='pending':raise CryptoError('Encrypted request unavailable')
        item=json.loads(row['payload'])
        request,signer=self._verify_item(db,item,item['thread'],now)
        files=[]
        if request['attachments']:
            directory=self.queue.state/'encrypted-files'
            directory.mkdir(mode=0o700,exist_ok=True)
            if directory.is_symlink() or directory.stat().st_mode&0o077:raise CryptoError('Unsafe attachment directory')
            directory=directory/request['request_id']
            directory.mkdir(mode=0o700,exist_ok=True)
            if directory.is_symlink() or directory.stat().st_mode&0o077:raise CryptoError('Unsafe attachment directory')
            for manifest in request['attachments']:
                plaintext=download(api,self.vault,item['thread'],manifest,signer,
                    check_authorized=lambda:self._verify_item(db,item,item['thread'],now))
                files.append(install(directory,manifest,plaintext))
        db.execute('BEGIN IMMEDIATE')
        try:
            fresh=db.execute('SELECT * FROM requests WHERE id=?',(ident,)).fetchone()
            if fresh is None or fresh['status']!='pending':raise CryptoError('Encrypted request no longer pending')
            self._verify_item(db,json.loads(fresh['payload']),item['thread'],now)
            db.execute('UPDATE requests SET files=? WHERE id=?',(json.dumps(files),ident))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        return files
