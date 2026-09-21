import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode
from cloud import workspace as m, domain as d

TOKEN = '123:synthetic-test-token'


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.s = d.initial(); self.s['bindings'] = {'owner': 10, 'friend': 20}
        self.project = 'project-example'
        self.catalog = {'project_id': self.project, 'threads': [
            {'id': 'thread-launcher', 'title': 'Launcher', 'project_id': self.project, 'status': 'idle'},
            {'id': 'thread-private1', 'title': 'Private', 'project_id': self.project, 'status': 'idle'}]}
        m.sync_catalog(self.s, self.catalog, self.project, 1000)
        self.body = {'thread': 'thread-launcher', 'text': 'Please check the log', 'request_id': 'unique-request-id-1'}

    def submit(self):
        return m.submit(self.s, 10, 'owner', self.body, 1001)

    def test_owner_submit_is_immediately_collectable_and_idempotent(self):
        item = m.submit(self.s, 10, 'owner', self.body, 1001)
        self.assertEqual(item['status'], 'queued')
        stored = self.s['items'][str(item['id'])]
        retry = m.submit(self.s, 10, 'owner', self.body, 1002)
        self.assertEqual(retry['id'], item['id'])
        self.assertEqual(len(self.s['items']), 1)
        self.assertEqual(m.collect(self.s, 1003, 'owner')['id'], item['id'])
        self.assertIsNone(m.collect(self.s, 1003, 'owner'))


    def test_owner_cannot_submit_to_read_only_task(self):
        self.catalog['threads'][0]['read_only'] = True
        m.sync_catalog(self.s, self.catalog, self.project, 1001)
        with self.assertRaises(m.Forbidden):
            m.submit(self.s, 10, 'owner', self.body, 1002)

    def test_read_only_task_keeps_history_access_but_rejects_dispatch(self):
        item=self.submit()
        self.catalog['threads'][0]['read_only']=True
        m.sync_catalog(self.s,self.catalog,self.project,1003)
        self.assertTrue(m.view(self.s,10,'owner',1004)['threads'][0]['read_only'])
        self.assertIsNone(m.collect(self.s,1004,'owner'))
        with self.assertRaises(m.Forbidden):self.submit()

    def test_initial_role_binding_is_one_time(self):
        with self.assertRaises(m.Forbidden): m.bind_user(self.s, {'id': 99, 'username': 'owner'}, 'owner')
        self.assertEqual(self.s['bindings']['owner'], 10)


    def test_idempotent_submit_and_payload_conflict(self):
        first = self.submit(); second = self.submit()
        self.assertEqual(first['id'], second['id'])
        with self.assertRaises(d.Rejected): m.submit(self.s, 10, 'owner', {**self.body, 'text': 'changed'}, 1002)

    def test_downloaded_request_rechecks_target_expiry_and_snapshot(self):
        item=self.submit()
        claim=m.collect(self.s,1003,'owner');d.receipt(self.s,claim,1004)
        body={k:item[k] for k in ('id','thread','snapshot')}
        self.assertEqual(m.dispatch_allowed(self.s,body,1005,'owner'),{'allowed':True})
        for change in ({'snapshot':'changed'},{'thread':'thread-private1'},{'id':-999}):
            self.assertFalse(m.dispatch_allowed(self.s,{**body,**change},1005,'owner')['allowed'])
        self.assertFalse(m.dispatch_allowed(self.s,body,1001+d.REQUEST_TTL,'owner')['allowed'])
        self.s['catalog'][item['thread']]['read_only']=True
        self.assertFalse(m.dispatch_allowed(self.s,body,1005,'owner')['allowed'])
        self.s['catalog'][item['thread']]['read_only']=False
        self.s['bindings']['owner']=99
        self.assertFalse(m.dispatch_allowed(self.s,body,1005,'owner')['allowed'])

    def test_other_project_catalog_rejected(self):
        with self.assertRaises(m.Forbidden): m.sync_catalog(self.s, {**self.catalog, 'project_id': 'work'}, self.project, 1000)
        body = {**self.catalog, 'threads': [{**self.catalog['threads'][0], 'project_id': 'work'}]}
        with self.assertRaises(d.Rejected): m.sync_catalog(self.s, body, self.project, 1000)

    def test_expired_and_rejected_not_delivered(self):
        item = self.submit()
        self.assertIsNone(m.collect(self.s, 1001 + d.REQUEST_TTL, 'owner'))

    def test_public_events_drop_unrelated_fields(self):
        event = m.public_event({'type': 'agent_message', 'text': 'Public answer',
                               'reasoning': 'private', 'raw_tool_output': 'private'}, 0)
        self.assertEqual(event, {'type': 'agent_message', 'id': '0', 'text': 'Public answer'})
        for path in ('/Users/private/file', '../secret', 'C:\\secret', 'sub/../../secret'):
            with self.assertRaises(d.Rejected):
                m.public_event({'type': 'file_change', 'change': 'edit', 'path': path}, 0)


if __name__ == '__main__': unittest.main()
