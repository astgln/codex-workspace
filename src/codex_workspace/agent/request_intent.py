"""Strict plaintext schema verified only after endpoint decryption."""
import json
import re

from codex_workspace.crypto.workspace_crypto import Context, CryptoError, decode

MAX_REQUEST_AGE = 24 * 60 * 60
FIELDS = frozenset(('v', 'workspace', 'thread', 'request_id', 'issued_at', 'expires_at', 'text', 'attachments'))
FILE_FIELDS = frozenset(('id', 'name', 'size', 'sha256', 'ciphertext_sha256'))


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise CryptoError('Invalid encrypted request')
        value[key] = item
    return value


def validate_request(plaintext: bytes, context: Context, now: int) -> dict:
    """Reject stale requests and ambiguous payloads before consuming their nonce."""
    context.wire()
    if len(plaintext) > 100000:
        raise CryptoError('Invalid encrypted request')
    try:
        value = json.loads(plaintext.decode('utf-8'), object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError):
        raise CryptoError('Invalid encrypted request') from None
    if (not isinstance(value, dict) or set(value) != FIELDS or type(value['v']) is not int or value['v'] != 1
            or value['workspace'] != context.workspace or value['thread'] != context.scope
            or value['request_id'] != context.record or context.kind != 'request' or context.revision != 1):
        raise CryptoError('Invalid encrypted request context')
    decode(value['request_id'], maximum=32, exact=32)
    issued, expires = value['issued_at'], value['expires_at']
    if (type(issued) is not int or type(expires) is not int or issued < 0 or issued > now + 60
            or expires <= now or not issued < expires <= issued + MAX_REQUEST_AGE):
        raise CryptoError('Encrypted request expired or has invalid dates')
    if not isinstance(value['text'], str) or len(value['text']) > 16000:
        raise CryptoError('Invalid encrypted request content')
    try:
        value['text'].encode('utf-8')
    except UnicodeError:
        raise CryptoError('Invalid encrypted request content') from None
    files = value['attachments']
    if not isinstance(files, list) or len(files) > 4 or (not value['text'].strip() and not files):
        raise CryptoError('Invalid encrypted attachments')
    ids = set()
    for file in files:
        validate_attachment(file)
        if file['id'] in ids:
            raise CryptoError('Duplicate encrypted attachment')
        ids.add(file['id'])
    return value


def validate_attachment(file):
    if not isinstance(file, dict) or set(file) != FILE_FIELDS:
        raise CryptoError('Invalid encrypted attachments')
    decode(file['id'], maximum=32, exact=32)
    name = file['name']
    if (not isinstance(name, str) or not 1 <= len(name) <= 200 or name in ('.', '..')
            or any(c in name for c in ('/', '\\')) or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise CryptoError('Invalid encrypted attachment name')
    try:
        if len(name.encode('utf-8')) > 200:
            raise CryptoError('Invalid encrypted attachment name')
    except UnicodeError:
        raise CryptoError('Invalid encrypted attachment name') from None
    if type(file['size']) is not int or not 1 <= file['size'] <= 5 * 1024 * 1024:
        raise CryptoError('Invalid encrypted attachment size')
    for field in ('sha256', 'ciphertext_sha256'):
        if not isinstance(file[field], str) or not re.fullmatch('[0-9a-f]{64}', file[field]):
            raise CryptoError('Invalid encrypted attachment digest')
