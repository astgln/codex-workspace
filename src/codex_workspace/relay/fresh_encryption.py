"""Offline, explicit fresh E2EE cutover. Discards old web content, not login keys."""
import argparse
import json
import os
from pathlib import Path
import shutil
from codex_workspace.domain import domain
from codex_workspace.relay.store import Store
from codex_workspace.relay.migrations import read_state, write_state
from codex_workspace.relay.opaque import _binary


def reset(directory,workspace):
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir():raise ValueError('Invalid data directory')
    _binary(workspace,32,32)
    marker=directory/'e2ee-mode.json'
    complete=directory/'e2ee-fresh-complete.json'
    mode={'v':1,'workspace':workspace}
    if complete.exists():
        if complete.is_symlink() or json.loads(complete.read_text())!=mode:raise ValueError('Cutover identity changed')
        return {'status':'already_complete'}
    if marker.exists():
        if marker.is_symlink() or json.loads(marker.read_text())!=mode:raise ValueError('Encryption identity changed')
    else:
        fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(mode,f);f.flush();os.fsync(f.fileno())
    fd=os.open(directory,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    # The pin is durable before content changes; crashes never re-enable old APIs.
    store=Store(directory);db=store.connect()
    try:
        db.execute('PRAGMA secure_delete=ON');db.execute('BEGIN IMMEDIATE')
        old=read_state(db);fresh=domain.initial();fresh['bindings']=old.get('bindings',{})
        write_state(db,fresh)
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('history_messages','history_threads','push_deliveries','push_answers','push_previews','pairing_mailbox'):
            if table in tables:db.execute('DELETE FROM '+table)
        # Never clear an already-populated ciphertext store on a retry.
        db.commit();db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('VACUUM');db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity check failed')
    finally:db.close()
    # Only paths owned by this application's old plaintext storage lifecycle.
    for name in ('uploads','migration-backups'):
        path=directory/name
        if path.is_symlink():raise ValueError('Unsafe old storage path')
        if path.exists():
            if not path.is_dir():raise ValueError('Unexpected old storage path')
            shutil.rmtree(path)
    fd=os.open(complete,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(mode,f);f.flush();os.fsync(f.fileno())
    return {'status':'complete'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--discard-old-web-content',action='store_true',required=True)
    args=parser.parse_args();os.umask(0o077)
    print(json.dumps(reset(args.directory,args.workspace)))

if __name__=='__main__':main()
