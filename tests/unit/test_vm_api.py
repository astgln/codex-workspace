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

    def test_collector_token_check_uses_configured_hash(self):
        for key in ('first-collector','second-collector'):
            with patch.dict('os.environ',{'CLIENT_KEY_HASH':hashlib.sha256(key.encode()).hexdigest()}):
                self.assertTrue(api.authorized({'headers':{'Authorization':'Bearer '+key}}))
                self.assertFalse(api.authorized({'headers':{'Authorization':'Workspace '+key}}))
                self.assertFalse(api.authorized({'headers':{'Authorization':'Bearer wrong'}}))
