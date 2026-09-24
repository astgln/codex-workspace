"""Exercise the real shell installer against disposable paths and fake services."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReleaseInstallTests(unittest.TestCase):
    def exercise(self, fail=False):
        root=Path(self.temp.name).resolve()
        checkout=Path(__file__).resolve().parents[2]
        base=root/'opt';release=base/'releases'/('a'*64)
        old=base/'releases'/('b'*64)
        release.mkdir(parents=True);old.mkdir()
        (old/'package-marker').write_text('running code')
        (base/'current').symlink_to(old)
        (root/'var').mkdir();(root/'var/workspace.sqlite3').touch()
        (root/'etc').mkdir();(root/'etc/config.json').write_text('{}')
        units=root/'units';units.mkdir()
        unit=units/'codex-workspace.service';unit.write_text('old unit')
        files=release/'ops/server';files.mkdir(parents=True)
        (files/'codex-workspace.service').write_text((checkout/'ops/server/codex-workspace.service').read_text())
        script=(checkout/'ops/server/install.sh').read_text()
        for before,after in [('/opt/codex-workspace',base),('/etc/codex-workspace',root/'etc'),('/etc/systemd/system',units),('/var/lib/codex-workspace',root/'var')]:
            script=script.replace(before,str(after))
        installer=root/'install.sh';installer.write_text(script)
        commands=root/'bin';commands.mkdir()
        runner=commands/'python3'
        runner.write_text('#!'+sys.executable+'\n'+'''import os,sys,json
from pathlib import Path
with open(os.environ['CALL_LOG'],'a') as out:out.write(json.dumps([sys.argv[0],*sys.argv[1:]])+'\\n')
if sys.argv[1:3]==['-m','venv']:
    target=Path(sys.argv[3])/'bin';target.mkdir(parents=True)
    for name in ('python','pip'):
        p=target/name;p.write_text(Path(__file__).read_text());p.chmod(0o755)
if 'codex_workspace.relay.migration_check' in sys.argv and os.environ.get('FAIL_REHEARSAL')=='1':sys.exit(1)
''')
        runner.chmod(0o755)
        for name in ('id','chmod','chown','systemctl'):
            path=commands/name;path.write_text('#!/bin/sh\nexit 0\n');path.chmod(0o755)
        env={**os.environ,'PATH':str(commands)+os.pathsep+os.environ['PATH'],'CALL_LOG':str(root/'calls'),'FAIL_REHEARSAL':str(int(fail))}
        result=subprocess.run(['sh',str(installer),str(release)],env=env,capture_output=True,text=True)
        self.assertEqual((old/'package-marker').read_text(),'running code')
        calls=[json.loads(line) for line in (root/'calls').read_text().splitlines()]
        self.assertTrue(any('codex_workspace.relay.migration_check' in c for c in calls))
        self.assertTrue(all(c[0].startswith(str(release/'.venv')) for c in calls[1:]))
        return result,base,release,old,unit,installer,env

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def test_failed_rehearsal_does_not_switch_running_release_or_unit(self):
        result,base,release,old,unit,*_=self.exercise(fail=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((base/'current').resolve(),old)
        self.assertEqual(unit.read_text(),'old unit')

    def test_success_pins_interpreter_and_assets_and_repeated_install_is_noop(self):
        result,base,release,old,unit,installer,env=self.exercise()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((base/'current').resolve(),release)
        text=unit.read_text()
        self.assertIn(str(release/'.venv/bin/python')+' -m uvicorn',text)
        self.assertIn('WORKSPACE_STATIC='+str(release/'static'),text)
        self.assertNotIn('@RELEASE_DIR@',text)
        calls=Path(env['CALL_LOG']).read_text()
        repeated=subprocess.run(['sh',str(installer),str(release)],env=env,capture_output=True,text=True)
        self.assertEqual(repeated.returncode,0,repeated.stderr)
        self.assertEqual(Path(env['CALL_LOG']).read_text(),calls)
