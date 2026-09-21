"""Strict key bundles for trusted endpoints. Never import from relay code."""
import json
import ipaddress
import re
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import UnsupportedAlgorithm

from workspace_crypto import Context, CryptoError, decode, encode, key_id, public_bytes, signer_id

MAX_KEYS = 10000


def read_object(raw: bytes):
    if not isinstance(raw, bytes) or len(raw) > 4 * 1024 * 1024:
        raise CryptoError('Invalid key material')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CryptoError('Invalid key material')
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise CryptoError('Invalid key material') from None
    if not isinstance(value, dict):
        raise CryptoError('Invalid key material')
    return value


def origin(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise CryptoError('Invalid workspace origin')
    try:
        parsed = urlsplit(value)
        host=parsed.hostname or ''
        try:
            address=ipaddress.ip_address(host)
            canonical_host='['+str(address)+']' if address.version==6 else str(address)
        except ValueError:
            canonical_host=host.lower()
            if not re.fullmatch('[a-z0-9.-]+',canonical_host) or canonical_host.rsplit('.',1)[-1].isdigit():
                raise ValueError()
        port=parsed.port
        canonical='https://'+canonical_host+(':'+str(port) if port is not None and port!=443 else '')
        valid = (parsed.scheme == 'https' and host and not parsed.username and not parsed.password
                 and not parsed.path and not parsed.query and not parsed.fragment and (port is None or port>0)
                 and value == canonical and not any(ord(c) <= 32 for c in value))
    except ValueError:
        valid = False
    if not valid:
        raise CryptoError('Invalid workspace origin')
    return value


def public_key(value):
    raw = decode(value, maximum=256)
    try:
        result = serialization.load_der_public_key(raw)
        if public_bytes(result) != raw:
            raise CryptoError('Invalid authority key')
        return result
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise CryptoError('Invalid authority key') from None


def private_key(value):
    raw = decode(value, maximum=512)
    try:
        result = serialization.load_der_private_key(raw, password=None)
        public_bytes(result)  # Requires P-256, not arbitrary private key types.
        canonical = result.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption())
        if raw != canonical:
            raise CryptoError('Invalid authority key')
        return result
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise CryptoError('Invalid authority key') from None


def key_entries(entries):
    if not isinstance(entries, list) or len(entries) > MAX_KEYS:
        raise CryptoError('Invalid scope keys')
    seen, ids = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'scope', 'epoch', 'key', 'id'}:
            raise CryptoError('Invalid scope keys')
        Context('validation', entry['scope'], 'key-wrap', 'validation', entry['epoch']).wire()
        raw = decode(entry['key'], maximum=32, exact=32)
        if entry['id'] != key_id(raw):
            raise CryptoError('Invalid scope key fingerprint')
        identity = (entry['scope'], entry['epoch'])
        if identity in seen or entry['id'] in ids:
            raise CryptoError('Duplicate scope key')
        seen.add(identity); ids.add(entry['id'])
    return entries


def validate_bundle(raw: bytes, *, workspace: str, expected_origin: str, device: str, authority: bytes):
    value = read_object(raw)
    if (set(value) != {'v', 'workspace', 'origin', 'device', 'authority', 'revision', 'keys'}
            or type(value['v']) is not int or value['v'] != 1 or value['workspace'] != workspace
            or value['origin'] != origin(expected_origin) or value['device'] != device
            or value['authority'] != encode(authority)):
        raise CryptoError('Key bundle does not match this device or workspace')
    decode(device, maximum=32, exact=32)
    public_key(value['authority'])
    Context(workspace, 'devices', 'key-wrap', device, value['revision']).wire()
    key_entries(value['keys'])
    return value
