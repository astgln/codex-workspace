"""Domain-separated device authentication signatures; no session or key storage."""
import json
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from codex_workspace.crypto.workspace_crypto import encode, decode, public_bytes, signer_id

DOMAIN = 'codex-workspace/device-auth/v1'

def message(kind, *values):
    return json.dumps([DOMAIN, kind, *values], ensure_ascii=False, separators=(',', ':')).encode()

def key(value):
    raw = decode(value, maximum=256)
    result = serialization.load_der_public_key(raw)
    if not isinstance(result, ec.EllipticCurvePublicKey) or not isinstance(result.curve, ec.SECP256R1) or public_bytes(result) != raw:
        raise ValueError('Invalid authentication key')
    return result

def sign(private, data):
    return encode(private.sign(data, ec.ECDSA(hashes.SHA256())))

def verify(public, signature, data, *, browser=False):
    raw = decode(signature, maximum=80)
    if browser:
        if len(raw) != 64: raise ValueError('Invalid authentication signature')
        raw = utils.encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
    public.verify(raw, data, ec.ECDSA(hashes.SHA256()))
