import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from worker_execution import execute


class ExecutionTests(unittest.TestCase):
    def test_private_outputs_and_literal_stdin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runner = Mock(return_value='result')
            original_umask = os.umask(0)
            try:
                self.assertEqual(execute(root, -1, ['codex', '-'], '$(untrusted)', '/working', runner), 'result')
            finally:
                os.umask(original_umask)
            args, kwargs = runner.call_args
            self.assertEqual(args, (['codex', '-'],))
            self.assertEqual(kwargs['input'], '$(untrusted)')
            self.assertEqual(kwargs['cwd'], '/working')
            self.assertNotIn('shell', kwargs)
            for path in (root / 'cli-runs').iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                execute(root, -1, ['codex'], 'retry', '/working', runner)
            self.assertEqual(runner.call_count, 1)

    def test_existing_stderr_prevents_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'cli-runs').mkdir()
            target = root / 'cli-runs/-1.stderr'
            target.write_text('existing diagnostic')
            runner = Mock()
            with self.assertRaises(FileExistsError):
                execute(root, -1, ['codex'], 'request', '/working', runner)
            runner.assert_not_called()
            self.assertEqual(target.read_text(), 'existing diagnostic')

    def test_progress_callback_runs_while_process_is_alive(self):
        import subprocess
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            process=Mock();process.__enter__=Mock(return_value=process);process.__exit__=Mock(return_value=False)
            process.communicate.side_effect=[subprocess.TimeoutExpired('cli',5),(None,None)]
            process.returncode=0
            progress=Mock()
            with patch('worker_execution.subprocess.Popen',return_value=process):
                result=execute(Path(folder),-1,['codex','-'],'request','/working',progress=progress)
            self.assertEqual(result.returncode,0)
            progress.assert_called_once()
            self.assertEqual(process.communicate.call_args_list[0].kwargs['input'],'request')
            self.assertIsNone(process.communicate.call_args_list[1].kwargs['input'])
