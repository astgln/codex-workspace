import copy
import unittest
from cloud import domain as d
from cloud import runtime
from unittest.mock import patch


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.s = d.initial()
        self.s['bindings'] = {'owner': 10, 'friend': 20}
        self.now = 1000

    def update(self, uid=1, text='test', sender=20, name='friend', edited=False):
        msg = {'from': {'id': sender, 'username': name}, 'chat': {'id': sender, 'type': 'private'},
               'message_id': 5, 'text': text}
        return {'update_id': uid, 'edited_message' if edited else 'message': msg}

    def ingest(self, update):
        d.ingest(self.s, update, self.now, 'owner', ['owner', 'friend'], 'thread')

    def card(self):
        job = d.take_send(self.s, self.now, 'owner')
        d.finish_send(self.s, job, 99)
        return job

    def approve(self, uid=2, sender=10, card=99, action='a'):
        item = self.s['items']['1']
        self.ingest({'update_id': uid, 'callback_query': {
            'from': {'id': sender}, 'data': action + ':' + item['nonce'],
            'message': {'message_id': card, 'chat': {'type': 'private', 'id': 10}}}})

    def test_no_delivery_without_approval(self):
        self.ingest(self.update())
        self.assertIsNone(d.claim(self.s, self.now))
        self.card()
        self.assertIsNone(d.claim(self.s, self.now))
        self.approve()
        self.assertEqual(d.claim(self.s, self.now)['text'], 'test')

    def test_foreign_callback_and_wrong_card(self):
        self.ingest(self.update()); self.card()
        self.approve(sender=20)
        self.approve(uid=3, card=100)
        self.assertIsNone(d.claim(self.s, self.now))

    def test_reject_and_expire(self):
        self.ingest(self.update()); self.card(); self.approve(action='r')
        self.assertIsNone(d.claim(self.s, self.now))
        self.approve(uid=3)
        self.assertEqual(self.s['items']['1']['status'], 'rejected')
        self.s['items']['1']['status'] = 'awaiting_approval'
        self.now += d.APPROVAL_TTL
        self.approve(uid=4)
        self.assertIsNone(d.claim(self.s, self.now))

    def test_edits_revoke_approval(self):
        self.ingest(self.update()); self.card(); self.approve()
        self.ingest(self.update(uid=3, text='modified', edited=True))
        self.assertIsNone(d.claim(self.s, self.now))
        self.assertEqual(self.s['items']['1']['text'], 'test')
        self.assertEqual(self.s['items']['1']['status'], 'superseded')

    def test_duplicate_callback_and_update(self):
        self.ingest(self.update()); before = copy.deepcopy(self.s)
        self.ingest(self.update()); self.assertEqual(self.s, before)
        self.card(); self.approve(); self.approve(uid=3, action='r')
        self.assertEqual(self.s['items']['1']['status'], 'approved')

    def test_username_cannot_rebind(self):
        self.ingest(self.update(sender=30))
        self.assertEqual(self.s['bindings']['friend'], 20)
        self.assertEqual(self.s['items'], {})

    def test_group_bot_attachments(self):
        for uid, field in enumerate(('group', 'bot', 'attachment')):
            update = self.update(uid=uid)
            if field == 'group': update['message']['chat']['type'] = 'group'
            if field == 'bot': update['message']['from']['is_bot'] = True
            if field == 'attachment': del update['message']['text']
            self.ingest(update)
        self.assertEqual(self.s['items'], {})

    def test_lease_restart_ack_idempotence_and_fixed_reply(self):
        self.ingest(self.update()); self.card(); self.approve()
        first = d.claim(self.s, self.now)
        self.assertIsNone(d.claim(self.s, self.now))
        second = d.claim(self.s, self.now + 121)
        with self.assertRaises(d.Rejected): d.receipt(self.s, first, self.now + 121)
        d.receipt(self.s, second, self.now + 121)
        d.receipt(self.s, second, self.now + 122)
        with self.assertRaises(d.Rejected): d.acknowledge(self.s, {'id': 1, 'thread': 'other'}, self.now)
        d.acknowledge(self.s, {'id': 1, 'thread': 'thread', 'text': 'evil', 'chat': 900}, self.now)
        job = d.take_send(self.s, self.now + 122, 'owner')
        self.assertEqual(job['params']['text'], d.ACK)
        self.assertEqual(job['params']['chat_id'], 20)

    def test_uncertain_not_retried(self):
        self.ingest(self.update())
        job = d.take_send(self.s, self.now, 'owner')
        d.finish_send(self.s, job, None)
        self.assertIsNone(d.take_send(self.s, self.now + 300, 'owner'))
        self.assertEqual(self.s['items']['1']['card'], 'uncertain')

    def test_crashed_send_not_retried(self):
        self.ingest(self.update()); d.take_send(self.s, self.now, 'owner')
        self.assertIsNone(d.take_send(self.s, self.now + 300, 'owner'))
        self.assertEqual(self.s['items']['1']['card'], 'uncertain')

    def test_capacity_fails_instead_of_dropping(self):
        self.ingest(self.update())
        with patch.object(d, 'MAX_ITEMS', 1):
            with self.assertRaises(d.Rejected): self.ingest(self.update(uid=3))
        self.assertNotIn('3', self.s['seen'])

    def test_http_auth_before_storage(self):
        with patch.dict('os.environ', {'CLIENT_KEY_HASH': '0' * 64, 'WEBHOOK_SECRET': 'secret'}):
            with patch.object(runtime, 'mutate') as store:
                self.assertEqual(runtime.api({'path': '/v1/inbox/claim'}, None)['statusCode'], 401)
                self.assertEqual(runtime.webhook({}, None)['statusCode'], 403)
                store.assert_not_called()


class LocalDeliveryTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from cloud_client import Inbox
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.inbox = Inbox(Path(self.temp.name))
        self.item = dict(id=1, text='untrusted', thread='thread', snapshot='hash', lease='first', created=1000)

    def test_not_pending_until_receipt(self):
        from unittest.mock import Mock
        api = Mock()
        self.inbox.receive(self.item, 'thread')
        self.assertEqual(self.inbox.pending('thread'), [])
        self.inbox.receipts(api)
        self.assertEqual(len(self.inbox.pending('thread')), 1)

    def test_reclaim_after_expired_lease(self):
        from unittest.mock import Mock
        from cloud_client import Conflict
        api = Mock(); api.call.side_effect = Conflict()
        self.inbox.receive(self.item, 'thread'); self.inbox.receipts(api)
        self.assertEqual(self.inbox.pending('thread'), [])
        self.item['lease'] = 'second'
        self.inbox.receive(self.item, 'thread')
        api.call.side_effect = None
        self.inbox.receipts(api)
        self.assertEqual(len(self.inbox.pending('thread')), 1)

    def test_replayed_receive_preserves_reply_state(self):
        from unittest.mock import Mock
        api = Mock(); self.inbox.receive(self.item, 'thread'); self.inbox.receipts(api)
        self.inbox.ack(1, 'thread'); self.inbox.receive(self.item, 'thread')
        self.assertEqual(self.inbox.pending('thread'), [])

if __name__ == '__main__': unittest.main()
