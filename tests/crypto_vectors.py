"""Ephemeral cross-language fixtures for browser tests. No production keys."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from workspace_crypto import (Context, create_recovery_code, decode, encode,
                              open_envelope, public_bytes, recovery_key, seal)

if sys.argv[1] == 'generate':
    private = ec.generate_private_key(ec.SECP256R1())
    symmetric = bytes(range(32))
    context = Context('test-workspace', 'test-task', 'history', 'test-record', 1)
    plaintext = 'Тест E2EE 🔐\u0000'.encode()
    recovery = create_recovery_code()
    print(json.dumps({'key': encode(symmetric), 'public': encode(public_bytes(private)),
        'private': encode(private.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption())),
        'context': context.wire(), 'plaintext': encode(plaintext),
        'envelope': seal(symmetric, private, context, plaintext),
        'recovery': recovery, 'recovery_key': encode(recovery_key(recovery))}))
elif sys.argv[1] == 'open':
    value = json.load(sys.stdin)
    public = serialization.load_der_public_key(decode(value['public'], maximum=256))
    plaintext = open_envelope(decode(value['key'], maximum=32), public,
                               Context(*value['context']), value['envelope'])
    print(json.dumps({'plaintext': encode(plaintext), 'recovery_key': encode(recovery_key(value['recovery']))}))
else:
    raise SystemExit('Unknown test operation')
