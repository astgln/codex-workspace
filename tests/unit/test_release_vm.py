"""Deployment cannot silently publish a different branch or dirty source."""
import unittest
from unittest.mock import Mock, patch
import codex_workspace.ops.release_vm as release_vm

class ReleaseTests(unittest.TestCase):
    def test_wrong_branch_stops_before_packaging_or_network(self):
        deployment=Mock(state={'release_branch':'experimental/multi-user'})
        with patch.object(release_vm,'deployment',return_value=deployment), patch.object(release_vm.subprocess,'check_output',return_value='main\n'), patch.object(release_vm.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'branch mismatch'):release_vm.publish()
            run.assert_not_called()
            deployment.checkpoint.assert_not_called()

    def test_dirty_checkout_stops_before_packaging_or_network(self):
        deployment=Mock(state={'release_branch':'experimental/multi-user'})
        with patch.object(release_vm,'deployment',return_value=deployment), patch.object(release_vm.subprocess,'check_output',side_effect=['experimental/multi-user\n',' M server/app.py\n']), patch.object(release_vm.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'Commit tracked'):release_vm.publish()
            run.assert_not_called()
