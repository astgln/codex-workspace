"""Opaque attachment chunks. Filenames and plaintext digests never reach this store."""
import hashlib
import json
import os
import threading
import time

from .opaque import Invalid, Conflict, _binary

CHUNK = 48 * 1024
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
LOCK = threading.RLock()


def _identity(body):
    if not isinstance(body, dict):raise Invalid('Invalid encrypted file')
    for field in ('workspace','scope'):
        value=body.get(field)
        try:valid=isinstance(value,str) and 0<len(value.encode('utf-8'))<=512
        except UnicodeError:valid=False
        if not valid:raise Invalid('Invalid encrypted file context')
    _binary(body.get('id'),32,32)
    return body['workspace'],body['scope'],body['id']


def _init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS opaque_files (
      workspace TEXT NOT NULL, scope TEXT NOT NULL, id TEXT NOT NULL,
      owner INTEGER NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, created INTEGER NOT NULL,
      ready INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(workspace,scope,id))''')


def handle(store, uid, action, body, *, collector=False):
    identity=_identity(body)
    if collector and action not in ('describe','get'):raise Invalid('Invalid encrypted file direction')
    with LOCK:
        db=store.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            _init(db)
            row=db.execute('SELECT owner,size,sha256,ready FROM opaque_files WHERE workspace=? AND scope=? AND id=?',identity).fetchone()
            if action=='start':
                import re
                if (set(body)!={'workspace','scope','id','size','sha256'} or type(body['size']) is not int
                        or not 0<body['size']<=MAX_FILE or not isinstance(body['sha256'],str)
                        or not re.fullmatch('[0-9a-f]{64}',body['sha256'])):
                    raise Invalid('Invalid encrypted upload')
                if row:
                    if row[:3]!=(uid,body['size'],body['sha256']):raise Conflict('Encrypted upload changed')
                else:
                    count,total=db.execute('SELECT count(*),coalesce(sum(size),0) FROM opaque_files').fetchone()
                    if count>=200 or total+body['size']>MAX_TOTAL:raise Conflict('Encrypted upload capacity')
                    db.execute('INSERT INTO opaque_files(workspace,scope,id,owner,size,sha256,created) VALUES(?,?,?,?,?,?,?)',
                               (*identity,uid,body['size'],body['sha256'],int(time.time())))
                db.commit()
                return {'id':identity[2],'chunk_size':CHUNK}
            if row is None or not collector and row[0]!=uid:raise Invalid('Encrypted upload unavailable')
            # Never derive filesystem components from arbitrary workspace/scope text.
            address=hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()
            directory=store.directory/'encrypted-uploads'/address
            if action=='describe':
                if set(body)!={'workspace','scope','id'} or not row[3]:raise Invalid('Encrypted upload incomplete')
                db.commit()
                return {'id':identity[2],'size':row[1],'sha256':row[2],'chunk_size':CHUNK}
            if action in ('chunk','get'):
                fields={'workspace','scope','id','index'} | ({'data'} if action=='chunk' else set())
                index=body.get('index')
                if set(body)!=fields or type(index) is not int or not 0<=index<(row[1]+CHUNK-1)//CHUNK:
                    raise Invalid('Invalid encrypted chunk')
                length=min(CHUNK,row[1]-index*CHUNK)
                if action=='chunk':
                    data=_binary(body['data'],CHUNK,length)
                    path=directory/str(index)
                    if row[3]:
                        if not path.is_file() or path.read_bytes()!=data:raise Conflict('Encrypted file is immutable')
                    else:
                        directory.mkdir(mode=0o700,parents=True,exist_ok=True)
                        try:
                            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                            with os.fdopen(fd,'wb') as output:
                                output.write(data);output.flush();os.fsync(output.fileno())
                        except FileExistsError:
                            if path.is_symlink() or path.read_bytes()!=data:raise Conflict('Encrypted chunk changed')
                    db.commit()
                    return {'ok':True}
                if not row[3]:raise Invalid('Encrypted upload incomplete')
                data=(directory/str(index)).read_bytes()
                if len(data)!=length:raise Invalid('Encrypted chunk damaged')
                import base64
                db.commit()
                return {'data':base64.urlsafe_b64encode(data).decode().rstrip('=')}
            if action=='finish':
                if set(body)!={'workspace','scope','id'}:raise Invalid('Invalid encrypted finish')
                digest=hashlib.sha256()
                for index in range((row[1]+CHUNK-1)//CHUNK):
                    path=directory/str(index)
                    if not path.is_file() or path.is_symlink():raise Invalid('Encrypted upload incomplete')
                    data=path.read_bytes()
                    if len(data)!=min(CHUNK,row[1]-index*CHUNK):raise Invalid('Encrypted upload incomplete')
                    digest.update(data)
                if digest.hexdigest()!=row[2]:raise Invalid('Encrypted upload digest mismatch')
                db.execute('UPDATE opaque_files SET ready=1 WHERE workspace=? AND scope=? AND id=?',identity)
                db.commit()
                return {'ok':True}
            raise Invalid('Unknown encrypted file action')
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
