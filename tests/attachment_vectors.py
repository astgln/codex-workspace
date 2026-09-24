"""Open browser-generated test attachments with Python; uses no real state."""
import hashlib
import json
from pathlib import Path
import sys

from codex_workspace.crypto.key_material import public_key
from codex_workspace.agent.request_intent import validate_attachment
from codex_workspace.crypto.workspace_crypto import Context, decode, open_envelope

value=json.load(sys.stdin)
manifest=value['manifest'];validate_attachment(manifest)
encrypted=decode(value['encrypted'],maximum=8*1024*1024)
if hashlib.sha256(encrypted).hexdigest()!=manifest['ciphertext_sha256']:raise SystemExit('Ciphertext digest mismatch')
envelope=json.loads(encrypted)
plaintext=open_envelope(decode(value['key'],maximum=32),public_key(value['public']),
    Context(value['workspace'],value['scope'],'attachment',manifest['id'],1),envelope)
if len(plaintext)!=manifest['size'] or hashlib.sha256(plaintext).hexdigest()!=manifest['sha256']:
    raise SystemExit('Plaintext digest mismatch')
print(json.dumps({'size':len(plaintext),'sha256':hashlib.sha256(plaintext).hexdigest()}))
