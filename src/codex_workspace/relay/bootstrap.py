"""Install non-secret service configuration; no external identity provider."""
import json
import os
from pathlib import Path
import sys


def install_pin(directory,value):
    from codex_workspace.crypto.device_auth import key
    from codex_workspace.crypto.workspace_crypto import decode
    if not isinstance(value,dict) or set(value)!={'workspace','authority'}:raise ValueError('Invalid authority pin')
    key(value['authority']);decode(value['workspace'],maximum=32,exact=32)
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    path=directory/'device-auth.json'
    if path.exists() or path.is_symlink():
        if path.is_symlink() or json.loads(path.read_text())!=value:raise ValueError('Refusing to replace authentication authority')
        return
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as output:json.dump(value,output)


def main():
    config=json.loads(Path(sys.argv[1]).read_text())
    config.pop('secret_id',None)
    config.pop('TELEGRAM_BOT_TOKEN',None)
    install_pin(Path('/var/lib/codex-workspace'),config.pop('auth_pin'))
    path=Path('/etc/codex-workspace/config.json')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as output:json.dump(config,output)


if __name__=='__main__':
    try:main()
    except Exception:
        print('Service secret initialization failed; details hidden',file=sys.stderr)
        raise SystemExit(1)
