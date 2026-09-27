import json,os,tempfile,unittest
from pathlib import Path
from codex_workspace.agent.task_relocation import apply,fingerprint
from codex_workspace.agent.runtime_support import BridgeError

class RelocationTests(unittest.TestCase):
    def test_explicit_relocation_preserves_restrictions_and_pins_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/'new';target.mkdir()
            state={'thread':'task','settings':{'cwd':'/old','runtime_workspace_roots':['/old'],
                'permission_profile':{'network':'restricted','file_system':{'entries':[
                    {'path':{'type':'path','path':'/old'},'access':'write'},
                    {'path':{'type':'path','path':'/old/.git'},'access':'read'},
                    {'path':{'type':'path','path':'/outside'},'access':'read'}]}}}}
            self.assertEqual(apply(state,root),state)
            p=root/'task-relocations.json';p.write_text(json.dumps({'task':{'from':'/old','to':str(target),'settings_sha256':fingerprint(state['settings'])}}));p.chmod(0o600)
            result=apply(state,root)['settings'];self.assertEqual(result['cwd'],str(target));self.assertEqual(result['runtime_workspace_roots'],[str(target)])
            entries=result['permission_profile']['file_system']['entries'];self.assertEqual(entries[1],{'path':{'type':'path','path':str(target/'.git')},'access':'read'});self.assertEqual(entries[2]['path']['path'],'/outside')
            self.assertEqual(result['permission_profile']['network'],'restricted');self.assertEqual(state['settings']['cwd'],'/old')
            state['settings']['permission_profile']['network']='enabled'
            with self.assertRaises(BridgeError):apply(state,root)
            p.chmod(0o644)
            with self.assertRaises(BridgeError):apply(state,root)
