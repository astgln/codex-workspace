"""Single-account HTTP boundary and migration from the formerly deployed schema."""
import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest
from codex_workspace.domain import workspace
from codex_workspace.relay import migrations, schema_legacy, sessions
from codex_workspace.relay.store import Store
from tests.unit.test_server import ServerTests

class AccountBoundaryTests(ServerTests):
    def test_old_cookie_is_denied_on_every_private_route(self):
        _, csrf = self.browser_session()
        with Store(self.temp.name).connect() as db:db.execute('DELETE FROM auth_registry')
        self.assertEqual(self.client.get('/auth/session').status_code,401)
        for route in ('e2ee/read','e2ee/send','e2ee/files/start','e2ee/files/get','e2ee/push/config','e2ee/push/subscribe'):
            with self.subTest(route=route):
                response=self.client.post('/web/'+route,json={},headers={'X-CSRF-Token':csrf})
                self.assertEqual(response.status_code,401)

    def test_retired_endpoints_are_absent(self):
        _, csrf = self.browser_session()
        for route in ('decisions','grants','member-policy'):
            self.assertEqual(self.client.post('/web/'+route,json={},headers={'X-CSRF-Token':csrf}).status_code,409)


class SchemaImportTests(unittest.TestCase):
    def test_schema3_preserves_content_and_invalidates_waiting_items(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'workspace.sqlite3'
            db=sqlite3.connect(path)
            db.executescript(Path('tests/fixtures/schema3.sql').read_text())
            before=migrations.read_state(db)
            db.close()
            from codex_workspace.relay.migration_check import prepare
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
