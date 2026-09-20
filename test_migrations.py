from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from server import migrations
from server.store import Store


@contextmanager
def database(path):
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'workspace.sqlite3'
        self.state = {
            'bindings': {'owner': 10, 'member': 20}, 'items': {}, 'seen': {},
            'project_grants': {'20': ['project']}, 'thread_grants': {'20': []},
            'thread_denies': {'20': ['private']},
            'member_policies': {'20': {'requires_approval': False}},
            'catalog': {'private': {'project_id': 'project'}}, 'unknown_future_field': [1, 'kept'],
        }
        with database(self.path) as db:
            db.execute('CREATE TABLE mailbox(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('INSERT INTO mailbox VALUES(1,?)', (json.dumps(self.state),))
            db.execute('CREATE TABLE unrelated(value TEXT)')
            db.execute("INSERT INTO unrelated VALUES('retained')")

    def test_migration_parity_reopen_and_no_duplicate_authority(self):
        for _ in range(2):
            store = Store(self.temp.name)
            self.assertEqual(store.mutate(copy.deepcopy), self.state)
        with database(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            residual = json.loads(db.execute('SELECT value FROM mailbox').fetchone()[0])
            self.assertFalse(set(migrations.SECTIONS) & residual.keys())
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT * FROM unrelated').fetchall(), [('retained',)])

    def test_interrupted_migration_is_atomic_and_retryable(self):
        original = migrations.write_state
        def fail_after_write(db, state):
            original(db, state)
            raise RuntimeError('simulated interruption')
        with patch.object(migrations, 'write_state', fail_after_write):
            with self.assertRaises(RuntimeError):
                Store(self.temp.name)
        with database(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(json.loads(db.execute('SELECT value FROM mailbox').fetchone()[0]), self.state)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='member_bindings'").fetchone())
        self.assertEqual(Store(self.temp.name).mutate(copy.deepcopy), self.state)

    def test_failed_mutation_rolls_back_access_and_residual_together(self):
        store = Store(self.temp.name)
        def mutate(state):
            state['bindings']['new'] = 30
            state['unknown_future_field'] = 'changed'
            state['member_policies']['20'] = {'requires_approval': 'invalid'}
        with self.assertRaises(ValueError):
            store.mutate(mutate)
        self.assertEqual(store.mutate(copy.deepcopy), self.state)

    def test_newer_schema_is_rejected_without_changes(self):
        with database(self.path) as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaises(RuntimeError):
            Store(self.temp.name)
        with database(self.path) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)

    def test_restore_keeps_post_migration_changes_and_other_tables(self):
        store = Store(self.temp.name)
        store.mutate(lambda state: state['thread_grants']['20'].append('new-task'))
        expected = store.mutate(copy.deepcopy)
        target = Path(self.temp.name) / 'restored.sqlite3'
        migrations.restore_legacy_copy(self.path, target)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with database(target) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
            self.assertEqual(json.loads(db.execute('SELECT value FROM mailbox').fetchone()[0]), expected)
            self.assertEqual(db.execute('SELECT * FROM unrelated').fetchall(), [('retained',)])
        with self.assertRaises(FileExistsError):
            migrations.restore_legacy_copy(self.path, target)
        self.assertEqual(store.mutate(copy.deepcopy), expected)
