"""Consistent private backup and migration rehearsal before a VM release."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

from . import migrations, schema_legacy


def prepare(source, backup_directory):
    source = Path(source).resolve()
    directory = Path(backup_directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = directory / ('pre-migration-' + uuid.uuid4().hex + '.sqlite3')
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as live:
        with closing(sqlite3.connect(backup)) as saved:
            live.backup(saved)
            if saved.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed')
    with tempfile.TemporaryDirectory(prefix='migration-check-', dir=directory) as temporary:
        trial = Path(temporary) / 'workspace.sqlite3'
        with closing(sqlite3.connect(backup)) as saved, closing(sqlite3.connect(trial)) as candidate:
            saved.backup(candidate)
            version = candidate.execute('PRAGMA user_version').fetchone()[0]
            if version == 0:
                row = candidate.execute('SELECT value FROM mailbox WHERE id=1').fetchone()
                before = json.loads(row[0]) if row else {'bindings': {}, 'items': {}, 'seen': {}}
            else:
                before = migrations.read_state(candidate)
            before = schema_legacy.normalize(before)
            candidate.execute('PRAGMA foreign_keys=ON')
            migrations.migrate(candidate)
            if migrations.read_state(candidate) != before:
                raise RuntimeError('Migration rehearsal parity failed')
            if candidate.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('Migration foreign key check failed')
        restored = Path(temporary) / 'restored.sqlite3'
        migrations.restore_legacy_copy(trial, restored)
        with closing(sqlite3.connect(restored)) as legacy:
            if json.loads(legacy.execute('SELECT value FROM mailbox WHERE id=1').fetchone()[0]) != before:
                raise RuntimeError('Restore rehearsal parity failed')
    return backup


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('backup_directory')
    args = parser.parse_args()
    path = prepare(args.source, args.backup_directory)
    print('Consistent backup and migration/restore rehearsal verified:', path.name)
