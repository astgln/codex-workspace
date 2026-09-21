"""Versioned authenticated envelopes for trusted endpoints, never the relay.

Transport integration is deliberately separate. A caller must supply the locally
trusted signing key and the expected context; envelope-provided trust is forbidden.
"""
import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


VERSION = 1
MAX_PLAINTEXT = 6 * 1024 * 1024
KINDS = frozenset(('request', 'response', 'history', 'catalog', 'attachment', 'push', 'key-wrap'))
FIELDS = frozenset(('v', 'context', 'key_id', 'signer', 'salt', 'nonce', 'ciphertext', 'signature'))
DOMAIN = b'codex-workspace/e2ee/v1'


class CryptoError(ValueError):
    """Deliberately content-free: safe to display without logging envelopes."""


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def decode(value, *, maximum: int, exact=None) -> bytes:
    if (not isinstance(value, str) or len(value) > (maximum * 4 + 2) // 3
            or not re.fullmatch(r'[A-Za-z0-9_-]*', value)):
        raise CryptoError('Invalid encrypted data')
    try:
        result = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except ValueError:
        raise CryptoError('Invalid encrypted data') from None
    if len(result) > maximum or (exact is not None and len(result) != exact) or encode(result) != value:
        raise CryptoError('Invalid encrypted data')
    return result


def _frame(*parts: bytes) -> bytes:
    return b''.join(len(part).to_bytes(4, 'big') + part for part in parts)


@dataclass(frozen=True)
class Context:
    workspace: str
    scope: str
    kind: str
    record: str
    revision: int

    def wire(self):
        values = (self.workspace, self.scope, self.kind, self.record)
        try:
            valid = all(isinstance(v, str) and 0 < len(v.encode('utf-8')) <= 512 for v in values)
        except UnicodeError:
            valid = False
        if (not valid or self.kind not in KINDS or type(self.revision) is not int
                or not 1 <= self.revision <= 9007199254740991):
            raise CryptoError('Invalid encrypted context')
        return [*values, self.revision]


def _symmetric_key(key):
    if not isinstance(key, bytes) or len(key) != 32:
        raise CryptoError('Invalid encryption key')


def key_id(key: bytes) -> str:
    _symmetric_key(key)
    return encode(hashlib.sha256(_frame(DOMAIN, b'key-id', key)).digest())


def public_bytes(key) -> bytes:
    if isinstance(key, ec.EllipticCurvePrivateKey):
        key = key.public_key()
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise CryptoError('Invalid signing key')
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def signer_id(key) -> str:
    return encode(hashlib.sha256(public_bytes(key)).digest())


def _aad(context: Context, kid: str, signer: str) -> bytes:
    values = context.wire()
    return _frame(DOMAIN, b'envelope', *(v.encode('utf-8') for v in values[:4]),
                  str(values[4]).encode('ascii'), kid.encode('ascii'), signer.encode('ascii'))


def _derive(key: bytes, salt: bytes, aad: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=_frame(DOMAIN, b'content-key', aad)).derive(key)


def _signed(aad, salt, nonce, ciphertext):
    return _frame(DOMAIN, b'signature', aad, salt, nonce, ciphertext)


def seal(key: bytes, signing_key, context: Context, plaintext: bytes) -> dict:
    """Encrypt bytes and authenticate their author and exact routing context."""
    _symmetric_key(key)
    if not isinstance(plaintext, bytes) or len(plaintext) > MAX_PLAINTEXT:
        raise CryptoError('Encrypted content exceeds size limit')
    if not isinstance(signing_key, ec.EllipticCurvePrivateKey):
        raise CryptoError('Invalid signing key')
    kid, signer = key_id(key), signer_id(signing_key)
    aad = _aad(context, kid, signer)
    salt, nonce = secrets.token_bytes(32), secrets.token_bytes(12)
    ciphertext = AESGCM(_derive(key, salt, aad)).encrypt(nonce, plaintext, aad)
    signature = signing_key.sign(_signed(aad, salt, nonce, ciphertext), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(signature)
    return {'v': VERSION, 'context': context.wire(), 'key_id': kid, 'signer': signer,
            'salt': encode(salt), 'nonce': encode(nonce), 'ciphertext': encode(ciphertext),
            'signature': encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}


def open_envelope(key: bytes, trusted_signer, expected: Context, envelope: dict) -> bytes:
    """No trust-on-first-use, no plaintext fallback, no caller-supplied algorithm."""
    _symmetric_key(key)
    if (not isinstance(envelope, dict) or set(envelope) != FIELDS or type(envelope['v']) is not int
            or envelope['v'] != VERSION or envelope['context'] != expected.wire()
            or not isinstance(envelope['context'], list)
            or type(envelope['context'][-1]) is not int
            or envelope['key_id'] != key_id(key) or envelope['signer'] != signer_id(trusted_signer)):
        raise CryptoError('Encrypted data verification failed')
    if not isinstance(trusted_signer, ec.EllipticCurvePublicKey):
        raise CryptoError('Invalid verification key')
    salt = decode(envelope['salt'], maximum=32, exact=32)
    nonce = decode(envelope['nonce'], maximum=12, exact=12)
    ciphertext = decode(envelope['ciphertext'], maximum=MAX_PLAINTEXT + 16)
    signature = decode(envelope['signature'], maximum=64, exact=64)
    if len(ciphertext) < 16:
        raise CryptoError('Invalid encrypted data')
    aad = _aad(expected, envelope['key_id'], envelope['signer'])
    der = encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big'))
    try:
        trusted_signer.verify(der, _signed(aad, salt, nonce, ciphertext), ec.ECDSA(hashes.SHA256()))
        return AESGCM(_derive(key, salt, aad)).decrypt(nonce, ciphertext, aad)
    except (InvalidSignature, InvalidTag, ValueError):
        raise CryptoError('Encrypted data verification failed') from None


def create_recovery_code() -> str:
    """256 random bits plus a transcription checksum; not an account password."""
    seed = secrets.token_bytes(32)
    checksum = hashlib.sha256(_frame(DOMAIN, b'recovery', seed)).digest()[:4]
    return 'cw1_' + encode(seed + checksum)


def recovery_key(code: str) -> bytes:
    if not isinstance(code, str) or not code.startswith('cw1_'):
        raise CryptoError('Invalid recovery key')
    raw = decode(code[4:], maximum=36, exact=36)
    checksum = hashlib.sha256(_frame(DOMAIN, b'recovery', raw[:32])).digest()[:4]
    if not hmac.compare_digest(raw[32:], checksum):
        raise CryptoError('Invalid recovery key')
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=_frame(DOMAIN, b'recovery-key')).derive(raw[:32])
