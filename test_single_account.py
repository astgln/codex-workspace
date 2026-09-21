"""Single-account HTTP boundary and migration from the formerly deployed schema."""
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from cloud import workspace
from server import migrations, schema_legacy, sessions
from server.store import Store
from test_server import ServerTests

class AccountBoundaryTests(ServerTests):
    def test_old_cookie_is_denied_on_every_private_route(self):
        _, csrf = self.browser_session()
        Store(self.temp.name).mutate(lambda s:s['bindings'].update(owner=99,other=42))
        self.assertEqual(self.client.get('/auth/session').status_code,403)
        for route in ('state','messages','history','uploads/start','uploads/get','push/config','push/subscribe','diagnostics'):
            with self.subTest(route=route):
                response=self.client.post('/web/'+route,json={},headers={'X-CSRF-Token':csrf})
                self.assertEqual(response.status_code,403)

    def test_retired_endpoints_are_absent(self):
        _, csrf = self.browser_session()
        for route in ('decisions','grants','member-policy'):
            self.assertEqual(self.client.post('/web/'+route,json={},headers={'X-CSRF-Token':csrf}).status_code,404)

    def test_other_verified_telegram_identity_cannot_login(self):
        from unittest.mock import patch
        challenge=self.client.get('/web/login/config').json()['challenge']
        with patch('cloud.login.verify_id_token',return_value={'id':20,'username':'other'}):
            response=self.client.post('/web/login/session',json={'challenge':challenge,'id_token':'test'})
        self.assertEqual(response.status_code,403)

class SchemaImportTests(unittest.TestCase):
    def test_schema3_preserves_content_and_invalidates_waiting_items(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'workspace.sqlite3'
            db=sqlite3.connect(path)
            db.executescript(Path('tests/fixtures/schema3.sql').read_text())
            before=migrations.read_state(db)
            db.close()
            from server.migration_check import prepare
            backup=prepare(path,Path(directory)/'backups')
            with sqlite3.connect(backup) as saved:
                self.assertEqual(saved.execute('PRAGMA user_version').fetchone()[0],3)
                self.assertEqual(migrations.read_state(saved),before)
            store=Store(directory)
            after=store.mutate(copy.deepcopy)
            self.assertEqual(after,schema_legacy.normalize(before))
            self.assertEqual(after['items']['-1']['status'],'queued')
            self.assertEqual(after['items']['-2']['status'],'expired')
            self.assertEqual(after['items']['-3']['events'][0]['text'],'synthetic answer')
            self.assertEqual(after['uploads']['file']['used_by'],-3)
            self.assertIsNone(workspace.collect(after,501,'different-account'))
            claim=workspace.collect(after,501,'owner')
            self.assertEqual(claim['id'],-1)
            with sqlite3.connect(path) as migrated:
                self.assertEqual(migrated.execute('SELECT text FROM preserved_history').fetchone()[0],'history survives')
                self.assertEqual(migrated.execute('PRAGMA foreign_key_check').fetchall(),[])
                self.assertIsNone(migrated.execute("SELECT name FROM sqlite_master WHERE name='access_grants'").fetchone())
