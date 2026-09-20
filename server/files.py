"""Private, bounded, immutable uploads. File contents are never executed."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from cloud import domain, workspace

CHUNK = 48 * 1024
MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
LOCK = threading.RLock()  # Service runs one worker; serializes finalize/chunk.


def public(upload):
    return {k:upload[k] for k in ('id','name','size','sha256')}


def start(state, uid, owner, body, now):
    thread = body.get('thread')
    if not workspace.can_submit(state,uid,owner,thread):
        raise workspace.Forbidden()
    name,size,digest,request_id = (body.get(k) for k in ('name','size','sha256','request_id'))
    if (not isinstance(name,str) or not 1 <= len(name) <= 200 or any(ord(c)<32 or c in '/\\' for c in name)
            or type(size) is not int or not 0 < size <= MAX_FILE
            or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)
            or not isinstance(request_id,str) or not re.fullmatch('[a-zA-Z0-9_-]{16,80}',request_id)):
        raise domain.Rejected('Invalid upload')
    uploads=state.setdefault('uploads',{})
    for upload in uploads.values():
        if upload['owner']==uid and upload['request_id']==request_id:
            if (upload['thread'],upload['name'],upload['size'],upload['sha256']) != (thread,name,size,digest):
                raise domain.Rejected('Upload idempotency conflict')
            return {**public(upload),'chunk_size':CHUNK}
    if len(uploads)>=200 or sum(u['size'] for u in uploads.values())+size>MAX_TOTAL:
        raise domain.Rejected('Upload storage quota')
    ident=secrets.token_hex(16)
    uploads[ident]=dict(id=ident,owner=uid,thread=thread,name=name,size=size,sha256=digest,
                       created=now,expires=now+domain.RETENTION,status='uploading',request_id=request_id)
    return {**public(uploads[ident]),'chunk_size':CHUNK}


def access(state, uid, owner, ident, now, write=False, collector=False):
    upload=state.get('uploads',{}).get(ident)
    if not upload or upload['expires']<=now:
        raise domain.Rejected('Upload expired')
    if collector:
        item=state['items'].get(str(upload.get('used_by')))
        if not item or not workspace.dispatch_allowed(state,item,now,owner)['allowed']:
            raise workspace.Forbidden()
    else:
        if upload['thread'] not in workspace.permitted_threads(state,uid,owner):
            raise workspace.Forbidden()
        if upload['owner']!=uid and (write or 'used_by' not in upload):
            raise workspace.Forbidden()
    if write and (upload['status']!='uploading' or 'used_by' in upload):
        raise domain.Rejected('Upload is immutable')
    return dict(upload)


def handle(store, uid, owner, action, body, collector=False):
    now=int(time.time())
    if action=='start' and not collector:
        return store.mutate(lambda s:start(s,uid,owner,body,now))
    ident=body.get('id')
    if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):
        raise domain.Rejected('Invalid upload ID')
    if action not in ('chunk','finish','get') or collector and action!='get':
        raise workspace.Forbidden()
    with LOCK:
        upload=store.mutate(lambda s:access(s,uid,owner,ident,now,write=action=='chunk',collector=collector))
        directory=store.directory/'uploads'/ident
        if action=='chunk':
            index=body.get('index')
            if type(index) is not int or not 0<=index<(upload['size']+CHUNK-1)//CHUNK:
                raise domain.Rejected('Invalid chunk')
            try:data=base64.b64decode(body.get('data',''),validate=True)
            except (ValueError,TypeError):raise domain.Rejected('Invalid chunk') from None
            if len(data)!=min(CHUNK,upload['size']-index*CHUNK):
                raise domain.Rejected('Chunk length mismatch')
            directory.mkdir(mode=0o700,parents=True,exist_ok=True)
            path=directory/str(index)
            try:
                fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'wb') as output:output.write(data)
            except FileExistsError:
                if path.read_bytes()!=data:raise domain.Rejected('Chunk is immutable')
            return {'ok':True}
        if action=='finish':
            if upload['owner']!=uid:
                raise workspace.Forbidden()
            digest=hashlib.sha256()
            for index in range((upload['size']+CHUNK-1)//CHUNK):
                path=directory/str(index)
                if not path.is_file():raise domain.Rejected('Upload incomplete')
                data=path.read_bytes()
                if len(data)!=min(CHUNK,upload['size']-index*CHUNK):raise domain.Rejected('Chunk length mismatch')
                digest.update(data)
            if digest.hexdigest()!=upload['sha256']:raise domain.Rejected('Upload hash mismatch')
            store.mutate(lambda s:s['uploads'][ident].update(status='ready'))
            return public(upload)
        index=body.get('index')
        if upload['status']!='ready' or type(index) is not int or not 0<=index<(upload['size']+CHUNK-1)//CHUNK:
            raise domain.Rejected('Invalid download')
        data=(directory/str(index)).read_bytes()
        return {'data':base64.b64encode(data).decode(),'chunk_size':CHUNK}


def cleanup(store):
    import shutil
    now=int(time.time())
    with LOCK:
        def remove(state):
            uploads=state.get('uploads',{})
            stale=[k for k,v in uploads.items() if v['expires']<=now]
            for ident in stale:del uploads[ident]
            return stale
        for ident in store.mutate(remove):
            if re.fullmatch('[a-f0-9]{32}',ident):
                shutil.rmtree(store.directory/'uploads'/ident,ignore_errors=True)
