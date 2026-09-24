import signal
import unittest
from unittest.mock import patch

from codex_workspace.agent.worker_lifecycle import shutdown_event


class LifecycleTests(unittest.TestCase):
    def test_signal_requests_stop_and_restores_previous_handlers(self):
        installed = {}
        def install(signum, handler):
            installed[signum] = handler
            return signal.SIG_DFL
        with patch('codex_workspace.agent.worker_lifecycle.signal.signal', side_effect=install):
            with shutdown_event() as stop:
                self.assertFalse(stop.is_set())
                installed[signal.SIGTERM](signal.SIGTERM, None)
                self.assertTrue(stop.is_set())
                self.assertTrue(stop.wait(30))
            self.assertEqual(installed, {signal.SIGTERM: signal.SIG_DFL, signal.SIGINT: signal.SIG_DFL})
