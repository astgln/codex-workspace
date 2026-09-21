from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from codex_workspace.relay import migrations
from codex_workspace.relay.store import Store


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
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], migrations.VERSION)
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

    def test_deployment_rehearsal_preserves_source_and_private_backup(self):
        from codex_workspace.relay.migration_check import prepare
        backup = prepare(self.path, Path(self.temp.name) / 'backups')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        for path in (self.path, backup):
            with database(path) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 0)
                self.assertEqual(json.loads(db.execute('SELECT value FROM mailbox').fetchone()[0]), self.state)

    def test_catalog_optional_fields_order_and_extensions_survive(self):
        self.state['projects'] = {'empty': {'id': 'empty', 'title': 'Empty'}}
        self.state['catalog'] = {
            'second': {'id':'second', 'project_id':'empty', 'title':'Second', 'status':'idle', 'read_only':False},
            'first': {'project_id':'empty', 'future': {'nested':[1, 2]}}}
        with database(self.path) as db:
            db.execute('UPDATE mailbox SET value=?', (json.dumps(self.state),))
        store = Store(self.temp.name)
        self.assertEqual(store.mutate(copy.deepcopy), self.state)
        self.assertEqual(list(store.mutate(copy.deepcopy)['catalog']), ['second','first'])
        with database(self.path) as db:
            residual = json.loads(db.execute('SELECT value FROM mailbox').fetchone()[0])
            self.assertNotIn('catalog', residual)
            self.assertNotIn('projects', residual)

    def test_upgrade_from_schema_one(self):
        store = Store(self.temp.name)
        with database(self.path) as db:
            state = migrations.read_state(db)
            migrations.request_store.drop(db)
            migrations.catalog_store.drop(db)
            db.execute('PRAGMA user_version=1')
            migrations.write_state(db, state)
        self.assertEqual(Store(self.temp.name).mutate(copy.deepcopy), self.state)

    def test_schema_two_preserves_delivered_request_files_and_response(self):
        self.state['items'] = {'-1': {
            'id': -1, 'source': 'web:20:request', 'channel': 'web', 'sender': 20,
            'thread': 'private', 'text': 'request', 'status': 'delivered',
            'created': 10, 'expires': 9999, 'snapshot': 'a'*64, 'lease': 'opaque-lease',
            'lease_until': 100, 'approved_by': 10, 'decision_at': 12,
            'result_revision': 2, 'result_status': 'completed',
            'events': [{'type':'agent_message','text':'reply'}, {'type':'error','message':'warning','severity':'warning'}],
            'attachments': [{'id':'file','name':'log.txt','size':3,'sha256':'b'*64}],
        }}
        self.state['uploads'] = {'file': {'id':'file','owner':20,'thread':'private',
            'name':'log.txt','size':3,'sha256':'b'*64,'status':'ready','used_by':-1,
            'request_id':'upload-nonce','created':10,'expires':9999}}
        store = Store(self.temp.name)
        store.mutate(lambda state: (state.clear(), state.update(copy.deepcopy(self.state))))
        # Reconstruct a schema-2 database, the currently deployed starting point.
        with database(self.path) as db:
            state = migrations.read_state(db)
            migrations.request_store.drop(db)
            db.execute('PRAGMA user_version=2')
            migrations.write_state(db, state)
        store = Store(self.temp.name)
        self.assertEqual(store.mutate(copy.deepcopy), self.state)
        with database(self.path) as db:
            self.assertEqual(db.execute('SELECT status,lease,result_revision FROM workspace_requests').fetchone(),
                             ('delivered','opaque-lease',2))
            self.assertEqual(db.execute('SELECT count(*) FROM request_events').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT used_by FROM workspace_uploads').fetchone()[0],-1)
            residual=json.loads(db.execute('SELECT value FROM mailbox').fetchone()[0])
            self.assertFalse({'items','uploads'} & residual.keys())
        restored = Path(self.temp.name) / 'legacy-with-request.sqlite3'
        migrations.restore_legacy_copy(self.path, restored)
        with database(restored) as db:
            self.assertEqual(json.loads(db.execute('SELECT value FROM mailbox').fetchone()[0]),self.state)

    def test_reads_and_heartbeats_do_not_rewrite_domain_tables(self):
        store = Store(self.temp.name)
        db = store.connect()
        statements = []
        db.set_trace_callback(statements.append)
        with patch.object(store, 'connect', return_value=db):
            store.mutate(copy.deepcopy)
        self.assertFalse(any(sql.startswith(('INSERT', 'DELETE', 'UPDATE')) for sql in statements))
        db = store.connect()
        statements.clear()
        db.set_trace_callback(statements.append)
        with patch.object(store, 'connect', return_value=db):
            store.mutate(lambda state: state.update(collector_seen=123))
        writes = [sql for sql in statements if sql.startswith(('INSERT', 'DELETE', 'UPDATE'))]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].startswith('INSERT OR REPLACE INTO mailbox'))
