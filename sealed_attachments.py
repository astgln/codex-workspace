"""Verify encrypted attachment bytes before writing any plaintext to disk."""
import hashlib
import json
import os
import tempfile

from request_intent import validate_attachment
from workspace_crypto import Context, CryptoError, decode, encode, key_id, open_envelope

CHUNK = 48 * 1024
MAX_ENCRYPTED_FILE = 8 * 1024 * 1024


def download(api, vault, scope, manifest, trusted_signer, *, check_authorized=lambda: None):
    validate_attachment(manifest)
    if api.url != vault.origin:
        raise CryptoError('Encrypted file origin changed')
    identity={'workspace':vault.workspace,'scope':scope,'id':manifest['id']}
    check_authorized()
    descriptor=api.call('/v2/e2ee/files/describe',identity)
    if (not isinstance(descriptor,dict) or set(descriptor)!={'id','size','sha256','chunk_size'}
            or descriptor['id']!=manifest['id'] or descriptor['sha256']!=manifest['ciphertext_sha256']
            or type(descriptor['size']) is not int or not 0<descriptor['size']<=MAX_ENCRYPTED_FILE
            or type(descriptor['chunk_size']) is not int or descriptor['chunk_size']!=CHUNK):
        raise CryptoError('Encrypted attachment metadata changed')
    encrypted=bytearray()
    for index in range((descriptor['size']+CHUNK-1)//CHUNK):
        check_authorized()
        response=api.call('/v2/e2ee/files/get',{**identity,'index':index})
        if not isinstance(response,dict) or set(response)!={'data'}:
            raise CryptoError('Invalid encrypted attachment chunk')
        encrypted.extend(decode(response['data'],maximum=CHUNK,exact=min(CHUNK,descriptor['size']-index*CHUNK)))
    if hashlib.sha256(encrypted).hexdigest()!=manifest['ciphertext_sha256']:
        raise CryptoError('Encrypted attachment digest mismatch')
    try:envelope=json.loads(encrypted.decode('utf-8'))
    except (ValueError,UnicodeError,RecursionError):raise CryptoError('Invalid encrypted attachment') from None
    if not isinstance(envelope,dict):raise CryptoError('Invalid encrypted attachment')
    # Old file epochs may remain readable, but only inside the requested scope.
    candidates=vault.db.execute('SELECT key FROM scope_keys WHERE scope=?',(scope,)).fetchall()
    matches=[row['key'] for row in candidates if key_id(row['key'])==envelope.get('key_id')]
    if len(matches)!=1:raise CryptoError('Attachment scope key is unavailable')
    plaintext=open_envelope(matches[0],trusted_signer,
                            Context(vault.workspace,scope,'attachment',manifest['id'],1),envelope)
    if len(plaintext)!=manifest['size'] or hashlib.sha256(plaintext).hexdigest()!=manifest['sha256']:
        raise CryptoError('Decrypted attachment digest mismatch')
    return plaintext


def install(directory, manifest, plaintext):
    """Caller chooses a private request directory, never a path from the relay."""
    validate_attachment(manifest)
    if len(plaintext)!=manifest['size'] or hashlib.sha256(plaintext).hexdigest()!=manifest['sha256']:
        raise CryptoError('Attachment content changed before installation')
    if directory.is_symlink() or directory.stat().st_mode&0o077:
        raise CryptoError('Attachments require a private local directory')
    target=directory/manifest['id']
    target.mkdir(mode=0o700,exist_ok=True)
    if target.is_symlink() or target.stat().st_mode&0o077:
        raise CryptoError('Unsafe attachment directory')
    path=target/manifest['name']
    fd,temporary=tempfile.mkstemp(prefix='.encrypted-download-',dir=target)
    try:
        with os.fdopen(fd,'wb') as output:
            output.write(plaintext);output.flush();os.fsync(output.fileno())
        try:
            os.link(temporary,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes()!=plaintext:
                raise CryptoError('Local attachment changed') from None
    finally:
        os.unlink(temporary)
    return {'id':manifest['id'],'name':manifest['name'],'path':str(path.absolute()),'sha256':manifest['sha256']}
