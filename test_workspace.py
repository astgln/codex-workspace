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
        self.project = 'project-warcraft'
        self.catalog = {'project_id': self.project, 'threads': [
            {'id': 'thread-launcher', 'title': 'Launcher', 'project_id': self.project, 'status': 'idle'},
            {'id': 'thread-private1', 'title': 'Private', 'project_id': self.project, 'status': 'idle'}]}
        m.sync_catalog(self.s, self.catalog, self.project, 1000)
        m.set_grants(self.s, 10, 'owner', {'user_id': 20, 'threads': ['thread-launcher']})
        self.body = {'thread': 'thread-launcher', 'text': 'Please check the log', 'request_id': 'unique-request-id-1'}

    def submit(self):
        return m.submit(self.s, 20, 'owner', self.body, 1001)

    def test_owner_submit_is_immediately_collectable_and_idempotent(self):
        item = m.submit(self.s, 10, 'owner', self.body, 1001)
        self.assertEqual(item['status'], 'approved')
        stored = self.s['items'][str(item['id'])]
        self.assertEqual((stored['approved_by'], stored['decision_at']), (10, 1001))
        retry = m.submit(self.s, 10, 'owner', self.body, 1002)
        self.assertEqual(retry['id'], item['id'])
        self.assertEqual(len(self.s['items']), 1)
        self.assertEqual(m.collect(self.s, 1003, 'owner')['id'], item['id'])
        self.assertIsNone(m.collect(self.s, 1003, 'owner'))

    def test_member_cannot_claim_owner_role_in_submission(self):
        item = m.submit(self.s, 20, 'owner', {
            **self.body, 'owner': True, 'role': 'owner', 'sender': 10,
            'status': 'approved', 'approved_by': 10}, 1001)
        self.assertEqual(item['status'], 'awaiting_approval')
        self.assertEqual(item['sender'], 20)
        self.assertIsNone(m.collect(self.s, 1002, 'owner'))

    def test_owner_cannot_submit_to_read_only_task(self):
        self.catalog['threads'][0]['read_only'] = True
        m.sync_catalog(self.s, self.catalog, self.project, 1001)
        with self.assertRaises(m.Forbidden):
            m.submit(self.s, 10, 'owner', self.body, 1002)

    def test_read_only_task_keeps_history_access_but_rejects_dispatch(self):
        item=self.submit()
        m.decision(self.s,10,'owner',{'id':item['id'],'snapshot':item['snapshot'],'decision':'approved'},1002)
        self.catalog['threads'][0]['read_only']=True
        m.sync_catalog(self.s,self.catalog,self.project,1003)
        self.assertTrue(m.view(self.s,20,'owner',1004)['threads'][0]['read_only'])
        self.assertIsNone(m.collect(self.s,1004,'owner'))
        with self.assertRaises(m.Forbidden):self.submit()

    def test_initial_role_binding_is_one_time(self):
        with self.assertRaises(m.Forbidden): m.bind_user(self.s, {'id': 99, 'username': 'owner'}, ['owner', 'friend'])
        self.assertEqual(self.s['bindings']['owner'], 10)

    def test_shared_messages_are_visible_only_with_thread_grant(self):
        self.submit()
        m.submit(self.s, 10, 'owner', {**self.body, 'request_id': 'owner-request-id-1', 'text': 'shared'}, 1002)
        m.submit(self.s, 10, 'owner', {**self.body, 'thread':'thread-private1', 'request_id':'private-message-id', 'text':'private'},1002)
        view = m.view(self.s, 20, 'owner', 1002)
        self.assertEqual([t['id'] for t in view['threads']], ['thread-launcher'])
        self.assertEqual(len(view['messages']), 2)
        self.assertNotIn('private',[item['text'] for item in view['messages']])
        m.set_grants(self.s,10,'owner',{'user_id':20,'threads':[]})
        self.assertEqual(m.view(self.s,20,'owner',1003)['messages'],[])
        self.assertNotIn('members', view)
        self.assertNotIn('nonce', view['messages'][0])
        self.assertNotIn('lease', view['messages'][0])

    def test_member_cannot_target_or_grant_private_thread(self):
        with self.assertRaises(m.Forbidden): m.submit(self.s, 20, 'owner', {**self.body, 'thread': 'thread-private1'}, 1001)
        with self.assertRaises(m.Forbidden): m.set_grants(self.s, 20, 'owner', {'user_id': 20, 'threads': ['thread-private1']})

    def test_owner_approval_exact_snapshot_and_target(self):
        item = self.submit()
        self.assertIsNone(m.collect(self.s, 1002, 'owner'))
        decision = {'id': item['id'], 'snapshot': item['snapshot'], 'decision': 'approved'}
        with self.assertRaises(m.Forbidden): m.decision(self.s, 20, 'owner', decision, 1003)
        with self.assertRaises(d.Rejected): m.decision(self.s, 10, 'owner', {**decision, 'snapshot': 'other'}, 1003)
        m.decision(self.s, 10, 'owner', decision, 1003)
        self.assertIsNone(d.claim(self.s, 1003, channel='telegram'))
        claim = m.collect(self.s, 1004, 'owner')
        self.assertEqual(claim['thread'], 'thread-launcher')
        self.assertIsNone(m.collect(self.s, 1004, 'owner'))
        d.receipt(self.s, claim, 1005)
        m.publish(self.s, {'id': item['id'], 'thread': item['thread'], 'revision': 1,
            'status': 'completed', 'events': [{'type': 'agent_message', 'text': 'Answer'}]}, 1006)
        self.assertEqual(m.view(self.s, 20, 'owner', 1007)['messages'][0]['events'][0]['text'], 'Answer')

    def test_revoke_grant_stops_claim(self):
        item = self.submit()
        m.decision(self.s, 10, 'owner', {'id': item['id'], 'snapshot': item['snapshot'], 'decision': 'approved'}, 1002)
        m.set_grants(self.s, 10, 'owner', {'user_id': 20, 'threads': []})
        self.assertIsNone(m.collect(self.s, 1003, 'owner'))

    def test_idempotent_submit_and_payload_conflict(self):
        first = self.submit(); second = self.submit()
        self.assertEqual(first['id'], second['id'])
        with self.assertRaises(d.Rejected): m.submit(self.s, 20, 'owner', {**self.body, 'text': 'changed'}, 1002)

    def test_downloaded_request_rechecks_grant_expiry_and_snapshot(self):
        item=self.submit()
        m.decision(self.s,10,'owner',{'id':item['id'],'snapshot':item['snapshot'],'decision':'approved'},1002)
        claim=m.collect(self.s,1003,'owner');d.receipt(self.s,claim,1004)
        body={k:item[k] for k in ('id','thread','snapshot')}
        self.assertEqual(m.dispatch_allowed(self.s,body,1005,'owner'),{'allowed':True})
        for change in ({'snapshot':'changed'},{'thread':'thread-private1'},{'id':-999}):
            self.assertFalse(m.dispatch_allowed(self.s,{**body,**change},1005,'owner')['allowed'])
        self.assertFalse(m.dispatch_allowed(self.s,body,1001+d.APPROVAL_TTL,'owner')['allowed'])
        self.s['catalog'][item['thread']]['read_only']=True
        self.assertFalse(m.dispatch_allowed(self.s,body,1005,'owner')['allowed'])
        self.s['catalog'][item['thread']]['read_only']=False
        m.set_grants(self.s,10,'owner',{'user_id':20,'threads':[]})
        self.assertFalse(m.dispatch_allowed(self.s,body,1005,'owner')['allowed'])

    def test_other_project_catalog_rejected(self):
        with self.assertRaises(m.Forbidden): m.sync_catalog(self.s, {**self.catalog, 'project_id': 'work'}, self.project, 1000)
        body = {**self.catalog, 'threads': [{**self.catalog['threads'][0], 'project_id': 'work'}]}
        with self.assertRaises(d.Rejected): m.sync_catalog(self.s, body, self.project, 1000)

    def test_expired_and_rejected_not_delivered(self):
        item = self.submit()
        with self.assertRaises(d.Rejected): m.decision(self.s, 10, 'owner', {'id': item['id'], 'snapshot': item['snapshot'], 'decision': 'approved'}, 1001 + d.APPROVAL_TTL)
        self.assertIsNone(m.collect(self.s, 1001 + d.APPROVAL_TTL, 'owner'))

    def test_public_events_drop_unrelated_fields(self):
        event = m.public_event({'type': 'agent_message', 'text': 'Public answer',
                               'reasoning': 'private', 'raw_tool_output': 'private'}, 0)
        self.assertEqual(event, {'type': 'agent_message', 'id': '0', 'text': 'Public answer'})
        for path in ('/Users/private/file', '../secret', 'C:\\secret', 'sub/../../secret'):
            with self.assertRaises(d.Rejected):
                m.public_event({'type': 'file_change', 'change': 'edit', 'path': path}, 0)


if __name__ == '__main__': unittest.main()
