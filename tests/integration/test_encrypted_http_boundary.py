"""HTTP regression matrix before retiring the pre-E2EE transport."""
import base64
import json
from pathlib import Path
import unittest
from tests.unit import test_server
from codex_workspace.relay.store import Store


class EncryptedHTTPBoundaryTests(unittest.TestCase):
    setUp=test_server.ServerTests.setUp
    tearDown=test_server.ServerTests.tearDown
    browser_session=test_server.ServerTests.browser_session

    def pin(self):
        value={'v':1,'workspace':base64.urlsafe_b64encode(b'w'*32).decode().rstrip('=')}
        path=Path(self.temp.name)/'e2ee-mode.json'
        path.write_text(json.dumps(value));path.chmod(0o600)
        return value

    def test_all_old_content_routes_are_rejected_without_changing_stored_data(self):
        self.pin()
        _,csrf=self.browser_session()
        store=Store(self.temp.name)
        before=store.mutate(lambda state:state)
        paths=('/web/state','/web/messages','/web/decisions','/web/grants','/web/member-policy',
               '/web/diagnostics','/web/history','/web/uploads/start','/web/uploads/chunk',
               '/web/uploads/finish','/web/uploads/get','/web/push/config','/v2/catalog',
               '/v2/inbox/claim','/v2/inbox/validate','/v2/inbox/ack','/v2/responses',
               '/v2/usage','/v2/worker/status','/v2/files/get','/v2/history/pending','/v2/history/publish')
        for path in paths:
            with self.subTest(path=path):
                response=self.client.post(path,json={'text':'private test payload'},headers={
                    'X-CSRF-Token':csrf,'Authorization':'Bearer collector-test-key'})
                self.assertEqual(response.status_code,409)
                self.assertEqual(response.json(),{'error':'encrypted_channel_required'})
        self.assertEqual(store.mutate(lambda state:state),before)

    def test_session_exposes_identity_and_mode_without_plaintext_workspace_content(self):
        mode=self.pin();self.browser_session()
        Store(self.temp.name).mutate(lambda state:state.update(weekly_quota={'private':'sample'},catalog={'private':{'id':'private','title':'private title'}}))
        response=self.client.get('/auth/session')
        self.assertEqual(response.status_code,200)
        view=response.json()['workspace']
        self.assertEqual(view['encryption'],mode)
        self.assertEqual(view['threads'],[])
        self.assertEqual(view['messages'],[])
        self.assertNotIn('weekly_quota',view)
        self.assertNotIn('private',json.dumps(view))

    def test_missing_pin_never_reenables_content_routes_or_session_payload(self):
        self.test_all_old_content_routes_are_rejected_without_changing_stored_data()
        (Path(self.temp.name)/'e2ee-mode.json').unlink()
        response=self.client.post('/web/state',json={})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.post('/v2/history/publish',json={}).status_code,409)
        response=self.client.get('/auth/session')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json(),{'error':'encryption_not_initialized'})
