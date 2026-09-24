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
