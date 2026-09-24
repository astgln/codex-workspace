import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from codex_workspace.ops.setup import initialize
from codex_workspace.relay.container import prepare
from codex_workspace.relay.store import Store
from codex_workspace.agent.workspace_client import API
from codex_workspace.agent.runtime_support import BridgeError

class ContainerTests(unittest.TestCase):
    def test_docker_setup_restart_and_identity_pins(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ):
            root=Path(temp);state=root/'agent';relay=root/'relay'
            initialize(state,'https://workspace.example.org',target='docker')
            self.assertFalse((state/'deployment.json').exists())
            config=state/'relay/relay.json';value=json.loads(config.read_text())
            self.assertEqual(set(value),{'OWNER_USERNAME','CLIENT_KEY_HASH','PROJECT_ID','PUBLIC_ORIGIN','auth_pin'})
            API(json.loads((state/'web.json').read_text()),state=state)
            prepare(config,relay);store=Store(relay)
            marker=(relay/'device-auth.json').read_bytes()
            prepare(config,relay)
            self.assertEqual(marker,(relay/'device-auth.json').read_bytes())
            value['PUBLIC_ORIGIN']='https://changed.example.org';config.write_text(json.dumps(value))
            with self.assertRaises(ValueError):prepare(config,relay)
            self.assertEqual(marker,(relay/'device-auth.json').read_bytes())

    def test_custom_https_validation_preserves_redirect_and_origin_boundary(self):
        from codex_workspace.crypto.key_material import origin
        for valid in ('https://workspace.example.org','https://workspace.example.org:8443','https://[::1]:8443'):
            self.assertEqual(origin(valid),valid)
        for invalid in ('http://example.org','https://a.example/path','https://user:password@example.org','https://example.org?x=y','https://example.org#x','https://EXAMPLE.org','https://example.org/'):
            with self.assertRaises(ValueError):origin(invalid)
            with self.assertRaises(BridgeError):API({'url':invalid},state=Path('/unused'))

    def test_setup_refuses_mixed_provider_settings_before_creating_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state'
            with self.assertRaises(ValueError):initialize(path,'https://example.org','folder','gateway',target='docker')
            self.assertFalse(path.exists())
