"""Current services must not load archived bot/controller transports."""
import subprocess
import sys
import unittest


class RuntimeBoundaryTests(unittest.TestCase):
    def test_service_imports_without_legacy_transports(self):
        source = '''
import sys
for name in ('bridge', 'cloud_client', 'cloud.runtime', 'legacy_shared_worker', 'shared_rpc'):
    sys.modules[name] = None
import cli_worker
import history_watch
import history_client
import web_client
'''
        result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
