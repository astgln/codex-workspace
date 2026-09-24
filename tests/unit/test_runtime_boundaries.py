"""Current services must not load archived bot/controller transports."""
import subprocess
import sys
import unittest


class RuntimeBoundaryTests(unittest.TestCase):
    def test_service_imports_without_legacy_transports(self):
        source = '''
import sys
for name in ('bridge', 'cloud_client', 'codex_workspace.domain.runtime', 'legacy_shared_worker', 'shared_rpc'):
    sys.modules[name] = None
import codex_workspace.agent.cli_worker
import codex_workspace.agent.history_watch
import codex_workspace.agent.history_client
import codex_workspace.agent.local_queue
'''
        result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
