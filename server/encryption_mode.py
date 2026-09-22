"""Operator-installed mode pin; legacy content endpoints fail closed after cutover."""
import json
from .opaque import _binary


def read(store):
    path=store.directory/'e2ee-mode.json'
    if not path.exists() and not path.is_symlink():return None
    if path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077 or path.stat().st_size>1024:
        raise ValueError('Invalid server encryption mode pin')
    value=json.loads(path.read_text())
    if not isinstance(value,dict) or set(value)!={'v','workspace'} or type(value['v']) is not int or value['v']!=1:
        raise ValueError('Unsupported server encryption mode')
    _binary(value['workspace'],32,32)
    return value


def permitted(path):
    if path.startswith(('web/e2ee/','v2/e2ee/')):return True
    if path in ('health','auth/session','auth/logout','web/login/config','web/login/session'):return True
    # Static assets only; unknown API namespaces never reach legacy handlers.
    return not path.startswith(('web/','v2/','auth/'))
