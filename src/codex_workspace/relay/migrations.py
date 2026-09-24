"""Transactional single-account schema. Older binaries must use their own database."""
import json
from codex_workspace.domain import domain
from . import catalog_store, request_store, schema_legacy

VERSION = 4
SECTIONS = ('bindings',)


def read_state(db):
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if 0 < version < VERSION:
        return schema_legacy.read_state(db)
    row = db.execute('SELECT value FROM mailbox WHERE id=1').fetchone()
    state = json.loads(row[0]) if row else domain.initial()
    if version == 0:
        return state
    state['bindings'] = dict(db.execute('SELECT username,uid FROM identity_bindings'))
    catalog_store.read(db, state)
    request_store.read(db, state)
    return state


def write_state(db, state, previous=None):
    def changed(keys):
        return previous is None or any((key in state) != (key in previous) or state.get(key) != previous.get(key) for key in keys)
    if changed(SECTIONS):
        db.execute('DELETE FROM identity_bindings')
        db.executemany('INSERT INTO identity_bindings VALUES(?,?)', state.get('bindings', {}).items())
    if changed(catalog_store.ENTITIES):
        catalog_store.write(db, state)
    if changed(request_store.ENTITIES):
        request_store.write(db, state)
    normalized = set(SECTIONS) | set(catalog_store.ENTITIES) | set(request_store.ENTITIES)
    residual = {k:v for k,v in state.items() if k not in normalized}
    if previous is None or residual != {k:v for k,v in previous.items() if k not in normalized}:
        db.execute('INSERT OR REPLACE INTO mailbox VALUES(1,?)', (json.dumps(residual, ensure_ascii=False),))


def migrate(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > VERSION:
            raise RuntimeError('Database schema is newer than this release')
        if version < VERSION:
            db.execute('CREATE TABLE IF NOT EXISTS mailbox(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
            original = schema_legacy.normalize(read_state(db))
            if version >= 3:
                request_store.drop(db)
            if version >= 2:
                catalog_store.drop(db)
            if version >= 1:
                schema_legacy.drop_access(db)
            db.execute('CREATE TABLE identity_bindings(username TEXT PRIMARY KEY,uid INTEGER NOT NULL)')
            catalog_store.create(db)
            request_store.create(db)
            db.execute('PRAGMA user_version=4')
            write_state(db, original)
            if read_state(db) != original:
                raise RuntimeError('Migration parity check failed')
        db.commit()
    except Exception:
        db.rollback()
        raise


def restore_legacy_copy(source, destination):
    """Make an exclusive, private v0 copy; never downgrade the live database.

Stop the service for a release rollback, invoke this with a new destination,
verify the output, then switch the old release to the restored directory.
"""
    import os
    from pathlib import Path
    import sqlite3

    source = Path(source).resolve()
    destination = Path(destination).resolve()
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        reader = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
        writer = sqlite3.connect(destination)
        try:
            reader.backup(writer)
            version = writer.execute('PRAGMA user_version').fetchone()[0]
            if version != VERSION:
                raise RuntimeError('Unsupported restore schema')
            writer.execute('BEGIN IMMEDIATE')
            state = read_state(writer)
            writer.execute('UPDATE mailbox SET value=? WHERE id=1', (json.dumps(state, ensure_ascii=False),))
            request_store.drop(writer)
            catalog_store.drop(writer)
            for table in ('identity_bindings',):
                writer.execute('DROP TABLE ' + table)
            writer.execute('PRAGMA user_version=0')
            writer.commit()
            if writer.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Restored database integrity check failed')
        finally:
            reader.close()
            writer.close()
    except Exception:
        destination.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Create a private legacy-schema database copy for rollback')
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    restore_legacy_copy(args.source, args.destination)
    print('Legacy database copy verified; data not printed')
