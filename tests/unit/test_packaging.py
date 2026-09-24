"""The installed package must not depend on a checkout or expose private files."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from codex_workspace.paths import state_directory
from codex_workspace.ops.install_cli_service import definition
from codex_workspace.ops.release_vm import release_files


class PackagingTests(unittest.TestCase):
    def test_service_uses_installed_module_and_explicit_state(self):
        value=definition(Path('/python'),Path('/codex'),Path('/catalog'),Path('/private/state'))
        self.assertEqual(value['ProgramArguments'][:5],['/python','-m','codex_workspace','agent','run'])
        self.assertEqual(value['EnvironmentVariables']['CODEX_WORKSPACE_STATE'],'/private/state')
        self.assertEqual(value['WorkingDirectory'],'/private/state')

    def test_commands_work_outside_checkout_without_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            env={**os.environ,'CODEX_WORKSPACE_STATE':directory+'/state'}
            for command in ([],['agent','run'],['history','watch'],['devices'],['service','install'],['deploy']):
                run=subprocess.run([sys.executable,'-m','codex_workspace',*command,'--help'],cwd=directory,env=env,capture_output=True,text=True)
                self.assertEqual(run.returncode,0,run.stderr)
            self.assertFalse(Path(directory,'state').exists())

    def test_state_is_independent_of_package_path(self):
        with patch.dict(os.environ,{'CODEX_WORKSPACE_STATE':'/explicit/state'}):
            self.assertEqual(state_directory(),Path('/explicit/state'))

    def test_release_excludes_credentials_tests_and_generated_python(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('pyproject.toml','src/codex_workspace/__init__.py','src/codex_workspace/relay/app.py','src/codex_workspace/secret.env','src/codex_workspace/cache.pyc','ops/server/install.sh','ops/server/codex-workspace.service','ops/server/settings.json','tests/test_x.py','.local/secret','web/dist/index.html'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            files=release_files(root)
            self.assertEqual(set(files),{'pyproject.toml','src/codex_workspace/__init__.py','src/codex_workspace/relay/app.py','ops/server/install.sh','ops/server/codex-workspace.service','static/index.html','static/files.json'})
