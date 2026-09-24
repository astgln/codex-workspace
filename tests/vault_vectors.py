"""Temporary authority fixtures for browser integration. Never reads real state."""
import json
from pathlib import Path
import sys
import tempfile

from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.crypto.workspace_crypto import create_recovery_code, decode, encode, public_bytes

value = json.load(sys.stdin)
with tempfile.TemporaryDirectory() as directory:
    with KeyVault.create(Path(directory) / 'vault.sqlite3', value['origin']) as vault:
        # Fixed workspace identity in this disposable fixture only.
        decode(value['workspace'], maximum=32, exact=32)
        vault.db.execute('UPDATE identity SET workspace=?', (value['workspace'],))
        vault.workspace = value['workspace']
        vault.scope_key('task-one')
        initial = json.loads(vault.bundle(decode(value['public'], maximum=256), {'task-one'}))
        vault.scope_key('task-one', rotate=True)
        latest = json.loads(vault.bundle(decode(value['public'], maximum=256), {'task-one'}))
        code = create_recovery_code()
        print(json.dumps({'initial': initial, 'latest': latest, 'recovery': vault.export_recovery(code), 'code': code}))
