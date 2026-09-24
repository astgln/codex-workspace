"""Local mode pin. Missing keys or dependencies cannot downgrade encryption."""
from pathlib import Path
import os
from codex_workspace.agent.runtime_support import BridgeError

def encrypted_required(directory: Path):
    marker = directory / 'e2ee-required'
    if not marker.exists() and not marker.is_symlink():
        return False
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_mode & 0o077 or marker.stat().st_uid != os.getuid() or marker.stat().st_nlink != 1 or marker.stat().st_size > 128:
        raise BridgeError('Invalid encryption mode pin')
    if marker.read_text() != 'codex-workspace/e2ee/v1\n':
        raise BridgeError('Unsupported encryption mode pin')
    return True
