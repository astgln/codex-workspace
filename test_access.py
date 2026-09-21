"""Authorization fails closed even for previously persisted identities."""
import unittest
from cloud import access, identity

class AccessTests(unittest.TestCase):
    def test_only_configured_identity_can_read_or_submit(self):
        state = {'bindings': {'owner': 1, 'other': 2}, 'catalog': {'task': {}}}
        for uid in (2, 99, None, True, '1'):
            with self.subTest(uid=uid):
                with self.assertRaises(access.Forbidden): access.permitted_threads(state, uid, 'owner')
                self.assertFalse(access.can_submit(state, uid, 'owner', 'task'))
        self.assertEqual(list(access.permitted_threads(state, 1, 'owner')), ['task'])
        self.assertTrue(access.can_submit(state, 1, 'owner', 'task'))
        state['catalog']['task']['read_only'] = True
        self.assertFalse(access.can_submit(state, 1, 'owner', 'task'))
        self.assertIn('task', access.permitted_threads(state, 1, 'owner'))

    def test_login_binds_once_then_uses_numeric_identity(self):
        state = {'bindings': {}}
        with self.assertRaises(access.Forbidden): identity.bind_user(state, {'id':2,'username':'other'}, 'owner')
        identity.bind_user(state, {'id':1,'username':'owner'}, 'owner')
        identity.bind_user(state, {'id':1,'username':'renamed'}, 'owner')
        with self.assertRaises(access.Forbidden): identity.bind_user(state, {'id':2,'username':'owner'}, 'owner')
