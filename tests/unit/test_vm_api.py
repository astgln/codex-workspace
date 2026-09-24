"""The VM application must operate without the retired cloud runtime."""
import hashlib
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from codex_workspace.relay import api


class VmApiTests(unittest.TestCase):
    def test_import_without_cloud_functions_runtime(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys; sys.modules['codex_workspace.domain.runtime'] = None; import codex_workspace.relay.app"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_collector_routes_cannot_touch_storage(self):
        with patch.dict('os.environ', {'CLIENT_KEY_HASH': hashlib.sha256(b'test-key').hexdigest()}):
            for path in ('/v1/inbox/claim', '/v1/inbox/ack', '/v1/replies'):
                with self.subTest(path=path):
                    def forbidden_store(operation):
                        self.fail('Legacy route reached storage')
                    result = api.api({'path': path, 'httpMethod': 'POST',
                        'headers': {'authorization': 'Bearer test-key'}, 'body': '{}'},
                        mutate=forbidden_store)
                    self.assertEqual(result['statusCode'], 404)

    def test_storage_is_per_call_not_global(self):
        with patch.dict('os.environ', {'CLIENT_KEY_HASH': hashlib.sha256(b'test-key').hexdigest(),
                                     'OWNER_USERNAME': 'owner'}):
            event = {'path': '/v2/inbox/claim', 'httpMethod': 'POST',
                     'headers': {'authorization': 'Bearer test-key'}, 'body': '{}'}
            for value in ('first-store', 'second-store'):
                result = api.api(event, mutate=lambda operation: value)
                self.assertEqual(json.loads(result['body'])['message'], value)
