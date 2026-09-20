"""Access matrix independent of HTTP routes and persistence adapters."""
import itertools
import unittest

from cloud import access


class AccessTests(unittest.TestCase):
    def test_member_grants_denies_and_read_only_matrix(self):
        for project, task, denied, read_only in itertools.product((False, True), repeat=4):
            with self.subTest(project=project, task=task, denied=denied, read_only=read_only):
                state = {
                    'bindings': {'owner': 1, 'member': 2},
                    'catalog': {'task': {'project_id': 'project', 'read_only': read_only}},
                    'project_grants': {'2': ['project'] if project else []},
                    'thread_grants': {'2': ['task'] if task else []},
                    'thread_denies': {'2': ['task'] if denied else []},
                }
                readable = (project or task) and not denied
                self.assertEqual('task' in access.permitted_threads(state, 2, 'owner'), readable)
                self.assertEqual(access.can_submit(state, 2, 'owner', 'task'), readable and not read_only)
                self.assertIn('task', access.permitted_threads(state, 1, 'owner'))
                self.assertEqual(access.can_submit(state, 1, 'owner', 'task'), not read_only)
                self.assertFalse(access.can_submit(state, 1, 'owner', 'missing'))
                with self.assertRaises(access.Forbidden):
                    access.can_submit(state, 3, 'owner', 'task')

    def test_approval_default_is_closed_and_only_explicit_false_disables_it(self):
        state = {'bindings': {'owner': 1, 'member': 2}}
        self.assertFalse(access.requires_approval(state, 1, 'owner'))
        self.assertTrue(access.requires_approval(state, 2, 'owner'))
        for value in (None, 0, '', 'false', True, False):
            state['member_policies'] = {'2': {'requires_approval': value}}
            self.assertEqual(access.requires_approval(state, 2, 'owner'), value is not False)
        with self.assertRaises(access.Forbidden):
            access.requires_approval(state, 3, 'owner')
