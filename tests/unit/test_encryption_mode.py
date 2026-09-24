import json
from pathlib import Path
from tests.unit.test_server import ServerTests
from codex_workspace.crypto.workspace_crypto import encode

class EncryptionModeTests(ServerTests):
    def test_cutover_blocks_plaintext_and_session_contains_no_history(self):
        _,csrf=self.browser_session()
        path=Path(self.temp.name)/'e2ee-mode.json'
        mode={'v':1,'workspace':encode(b'w'*32)}
        path.write_text(json.dumps(mode));path.chmod(0o600)
        for route in ('web/state','web/messages','web/history','v2/catalog','v2/responses','web/push/test'):
            response=self.client.post('/'+route,json={},headers={'X-CSRF-Token':csrf,'Authorization':'Bearer collector-test-key'})
            self.assertEqual(response.status_code,409,route)
        response=self.client.get('/auth/session').json()['workspace']
        self.assertEqual(response['encryption'],mode)
        self.assertEqual(response['messages'],[])
        self.assertEqual(response['threads'],[])
        path.write_text('broken')
        self.assertEqual(self.client.get('/auth/session').status_code,503)
