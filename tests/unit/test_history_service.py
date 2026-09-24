"""Encrypted service preserves its checkpoint across one-shot invocations."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from codex_workspace.agent.history_watch import main

class HistoryServiceTests(TestCase):
    def test_encrypted_once_retains_checkpoint_and_uses_only_encrypted_adapter(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'web.json').write_text(json.dumps({'paused':False,'project_id':'install'}))
            pin=root/'e2ee-required';pin.write_text('codex-workspace/e2ee/v1\n');pin.chmod(0o600)
            checkpoint=root/'encrypted-history-watch.json'
            checkpoint.write_text(json.dumps({'previous':'retained'}))
            catalog={'project_id':'install','threads':[]};adapter=Mock()
            def sync(api, actual, project, sessions, cache, failures, service_failures):
                self.assertIs(api,adapter)
                self.assertEqual(actual,catalog)
                self.assertEqual(cache,{'previous':'retained'})
                cache['next']='written'
                return 0
            with patch('sys.argv',['history','--once','--state',str(root),'--catalog',str(root/'catalog.json')]), patch('codex_workspace.agent.history_watch.API') as network, patch('codex_workspace.devices.key_vault.KeyVault'), patch('codex_workspace.agent.sealed_history.EncryptedHistoryAPI',return_value=adapter), patch('codex_workspace.agent.history_watch.refresh',return_value=catalog), patch('codex_workspace.agent.history_watch.sync_once',side_effect=sync):
                main()
                network.return_value.call.assert_not_called()
            self.assertEqual(json.loads(checkpoint.read_text()),{'previous':'retained','next':'written'})
            self.assertFalse((root/'history-watch.json').exists())
