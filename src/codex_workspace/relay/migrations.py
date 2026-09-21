"""Transactional schema migrations and the transitional state adapter.

Access tables are authoritative after version 1. The residual mailbox contains
only domains not migrated yet. Never run an older release against this schema.
"""
import json
from codex_workspace.domain import domain
from . import catalog_store, request_store

VERSION = 3
GRANTS = ('thread_grants', 'project_grants', 'thread_denies')
SECTIONS = ('bindings', *GRANTS, 'member_policies')


def read_state(db):
    row = db.execute('SELECT value FROM mailbox WHERE id=1').fetchone()
    state = json.loads(row[0]) if row else domain.initial()
    for section, in db.execute('SELECT name FROM access_sections'):
        state[section] = {}
    for name, uid in db.execute('SELECT username,uid FROM member_bindings'):
        state['bindings'][name] = uid
    for kind, uid in db.execute('SELECT kind,uid FROM grant_subjects'):
        state[kind][uid] = []
    for kind, uid, target in db.execute('SELECT kind,uid,target FROM access_grants ORDER BY position'):
        state[kind][uid].append(target)
    for uid, required in db.execute('SELECT uid,requires_approval FROM member_policies'):
        state['member_policies'][uid] = {'requires_approval': bool(required)}
    if db.execute('PRAGMA user_version').fetchone()[0] >= 2:
        catalog_store.read(db, state)
    if db.execute('PRAGMA user_version').fetchone()[0] >= 3:
        request_store.read(db, state)
    return state


def write_state(db, state, previous=None):
    def changed(sections):
        return previous is None or any((key in state) != (key in previous) or state.get(key) != previous.get(key) for key in sections)

    if changed(SECTIONS):
        # Caller owns the transaction, including all domain mutations.
        for table in ('access_grants', 'grant_subjects', 'member_bindings', 'member_policies', 'access_sections'):
            db.execute('DELETE FROM ' + table)
        db.executemany('INSERT INTO access_sections VALUES(?)', [(s,) for s in SECTIONS if s in state])
        db.executemany('INSERT INTO member_bindings VALUES(?,?)', state.get('bindings', {}).items())
        for kind in GRANTS:
            for uid, targets in state.get(kind, {}).items():
                db.execute('INSERT INTO grant_subjects VALUES(?,?)', (kind, uid))
                db.executemany('INSERT INTO access_grants VALUES(?,?,?,?)',
                               [(kind, uid, target, pos) for pos, target in enumerate(targets)])
        for uid, policy in state.get('member_policies', {}).items():
            if set(policy) != {'requires_approval'} or type(policy['requires_approval']) is not bool:
                raise ValueError('Invalid stored member policy')
            db.execute('INSERT INTO member_policies VALUES(?,?)', (uid, int(policy['requires_approval'])))
    normalized = set(SECTIONS)
    if db.execute('PRAGMA user_version').fetchone()[0] >= 2:
        if changed(catalog_store.ENTITIES):
            catalog_store.write(db, state)
        normalized.update(catalog_store.ENTITIES)
    if db.execute('PRAGMA user_version').fetchone()[0] >= 3:
        if changed(request_store.ENTITIES):
            request_store.write(db, state)
        normalized.update(request_store.ENTITIES)
    residual = {key: value for key, value in state.items() if key not in normalized}
    old_residual = None if previous is None else {key:value for key,value in previous.items() if key not in normalized}
    if residual != old_residual:
        db.execute('INSERT OR REPLACE INTO mailbox(id,value) VALUES(1,?)',
                   (json.dumps(residual, ensure_ascii=False),))



def migrate(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version > VERSION:
            raise RuntimeError('Database schema is newer than this release')
        if version == 0:
            db.execute('CREATE TABLE IF NOT EXISTS mailbox(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
            row = db.execute('SELECT value FROM mailbox WHERE id=1').fetchone()
            original = json.loads(row[0]) if row else domain.initial()
            statements = (
                'CREATE TABLE access_sections(name TEXT PRIMARY KEY)',
                'CREATE TABLE member_bindings(username TEXT PRIMARY KEY,uid INTEGER NOT NULL)',
                "CREATE TABLE grant_subjects(kind TEXT NOT NULL CHECK(kind IN ('thread_grants','project_grants','thread_denies')),uid TEXT NOT NULL,PRIMARY KEY(kind,uid))",
                'CREATE TABLE access_grants(kind TEXT NOT NULL,uid TEXT NOT NULL,target TEXT NOT NULL,position INTEGER NOT NULL,PRIMARY KEY(kind,uid,target),FOREIGN KEY(kind,uid) REFERENCES grant_subjects(kind,uid) ON DELETE CASCADE)',
                'CREATE TABLE member_policies(uid TEXT PRIMARY KEY,requires_approval INTEGER NOT NULL CHECK(requires_approval IN (0,1)))',
            )
            for statement in statements:
                db.execute(statement)
            write_state(db, original)
            if read_state(db) != original:
                raise RuntimeError('Migration state parity check failed')
            db.execute('PRAGMA user_version=1')
            version = 1
        if version == 1:
            original = read_state(db)
            catalog_store.create(db)
            db.execute('PRAGMA user_version=2')
            write_state(db, original)
            if read_state(db) != original:
                raise RuntimeError('Catalog migration parity check failed')
            version = 2
        if version == 2:
            original = read_state(db)
            request_store.create(db)
            db.execute('PRAGMA user_version=3')
            write_state(db, original)
            if read_state(db) != original:
                raise RuntimeError('Request migration parity check failed')
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
            for table in ('access_grants', 'grant_subjects', 'member_bindings', 'member_policies', 'access_sections'):
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
