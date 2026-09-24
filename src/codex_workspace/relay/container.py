"""Non-root container startup with pinned identity and durable E2EE state."""
import json
import os
from pathlib import Path
import re
import sqlite3
from codex_workspace.crypto.key_material import origin
from codex_workspace.relay.bootstrap import install_pin, install_mode


def prepare(config_path, directory):
    config=json.loads(Path(config_path).read_text())
    expected={'OWNER_USERNAME','CLIENT_KEY_HASH','PROJECT_ID','PUBLIC_ORIGIN','auth_pin'}
    if not isinstance(config,dict) or set(config)!=expected:raise ValueError('Unexpected relay configuration')
    origin(config['PUBLIC_ORIGIN'])
    if not re.fullmatch(r'[a-z0-9_]{5,32}',config['OWNER_USERNAME']):raise ValueError('Invalid owner label')
    if not re.fullmatch(r'[a-f0-9]{64}',config['CLIENT_KEY_HASH']):raise ValueError('Invalid transport hash')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',config['PROJECT_ID']):raise ValueError('Invalid installation ID')
    directory=Path(directory)
    if directory.is_symlink():raise ValueError('Unsafe data directory')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(directory,0o700)
    # Prevent accidental reuse of a volume under a different origin/catalog.
    identity={'origin':config['PUBLIC_ORIGIN'],'project':config['PROJECT_ID'],'owner':config['OWNER_USERNAME']}
    marker=directory/'installation.json'
    if marker.exists() or marker.is_symlink():
        if marker.is_symlink() or json.loads(marker.read_text())!=identity:raise ValueError('Container identity changed')
    else:
        fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as output:json.dump(identity,output)
    install_pin(directory,config['auth_pin'])
    install_mode(directory,config['auth_pin']['workspace'])
    database=directory/'workspace.sqlite3'
    if database.exists():
        from codex_workspace.relay.migrations import VERSION
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
            version=db.execute('PRAGMA user_version').fetchone()[0]
        if version>VERSION:raise ValueError('Downgrade refused')
        if version<VERSION:
            from codex_workspace.relay.migration_check import prepare as rehearse
            rehearse(database,directory/'migration-backups')
    for key in expected-{'auth_pin'}:os.environ[key]=config[key]


def main():
    os.umask(0o077)
    try:prepare(os.environ['WORKSPACE_CONFIG'],os.environ['WORKSPACE_DATA'])
    except Exception:raise SystemExit('Container initialization refused; check configuration, volume identity and permissions. Details hidden.') from None
    import uvicorn
    uvicorn.run('codex_workspace.relay.app:app',host='0.0.0.0',port=8080,workers=1,
                access_log=False,log_level='warning',proxy_headers=False)

if __name__=='__main__':main()
