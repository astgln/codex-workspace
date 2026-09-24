"""Network boundary rejects obsolete payload routes before building a request."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from codex_workspace.agent.runtime_support import BridgeError
from codex_workspace.agent.workspace_client import API

class TransportBoundaryTests(TestCase):
    def test_plaintext_is_rejected_with_pinned_encryption_and_no_keys(self):
        with TemporaryDirectory() as temp:
            state=Path(temp)
            pin=state/'e2ee-required'
            pin.write_text('codex-workspace/e2ee/v1\n');pin.chmod(0o600)
            api=object.__new__(API);api.state=state
            with patch('urllib.request.build_opener') as network:
                for path in ('/v2/catalog','/v2/inbox/claim','/v2/history/publish','/v2/files/get','/v2/usage','/v2/worker/status'):
                    with self.subTest(path=path),self.assertRaises(BridgeError):
                        api.call(path,{'text':'must stay local'})
                network.assert_not_called()

    def test_damaged_pin_never_enables_a_network_request(self):
        with TemporaryDirectory() as temp:
            state=Path(temp)
            pin=state/'e2ee-required';pin.write_text('invalid');pin.chmod(0o600)
            api=object.__new__(API);api.state=state
            with patch('urllib.request.build_opener') as network:
                with self.assertRaises(BridgeError):api.call('/v2/e2ee/read',{})
                network.assert_not_called()

    def test_missing_pin_does_not_enable_plaintext_network_routes(self):
        with TemporaryDirectory() as temp:
            api=object.__new__(API);api.state=Path(temp)
            with patch('urllib.request.build_opener') as network:
                for path in ('/v2/catalog','/v2/history/publish','/v2/inbox/claim','/v2/usage'):
                    with self.subTest(path=path),self.assertRaises(BridgeError):api.call(path,{})
                network.assert_not_called()

    def test_collector_without_encryption_does_not_open_queue_or_network(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock
        from codex_workspace.agent.cli_worker import serve
        with TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'web.json').write_text(json.dumps({'paused':False,'project_id':'installation'}))
            catalog=root/'catalog.json';catalog.write_text(json.dumps({'project_id':'installation'}))
            args=SimpleNamespace(state=root,catalog=catalog,codex=None,once=True,interval=1)
            stop=Mock();stop.is_set.return_value=False
            with patch('codex_workspace.agent.cli_worker.API') as api:
                self.assertEqual(serve(args,root,stop),1)
                api.assert_not_called()
            self.assertFalse((root/'web-queue.sqlite3').exists())
