import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from bridge import Queue, BridgeError, ACK, check_bot, exclusive, read_token, Telegram, bind_usernames


def update(uid=10, user=123, text='тест', kind='private'):
    return {'update_id':uid,'message':{'message_id':100+uid,'from':{'id':user,'is_bot':False},
                                      'chat':{'id':user,'type':kind},'text':text}}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name); self.q=Queue(self.path)

    def tearDown(self):
        self.q.db.close(); self.tmp.cleanup()

    def test_env_is_data_and_requires_private_permissions(self):
        env=self.path/'.env'
        env.write_text('TELEGRAM_BOT_TOKEN="123:synthetic_test_token"\n')
        env.chmod(0o600)
        self.assertEqual(read_token(env),'123:synthetic_test_token')
        env.chmod(0o644)
        with self.assertRaises(BridgeError):read_token(env)
        env.chmod(0o600); env.write_text('TELEGRAM_BOT_TOKEN=$(echo bad)\n')
        with self.assertRaises(BridgeError):Telegram(read_token(env))

    def test_username_binding_uses_sender_not_text_and_is_one_time(self):
        config={'allowed':[], 'pending_usernames':['approved_name']}
        msg=update(text='@approved_name')
        self.assertFalse(bind_usernames(config,[msg]))
        msg['message']['from']['username']='APPROVED_NAME'
        self.assertTrue(bind_usernames(config,[msg]))
        self.assertEqual(config['allowed'],[123])
        other=update(user=999);other['message']['from']['username']='approved_name'
        self.assertFalse(bind_usernames(config,[other]))
        self.assertEqual(config['allowed'],[123])

    def test_username_binding_rejects_group_and_bot(self):
        config={'allowed':[], 'pending_usernames':['approved_name']}
        msg=update(kind='group');msg['message']['from']['username']='approved_name'
        self.assertFalse(bind_usernames(config,[msg]))
        msg['message']['chat']['type']='private';msg['message']['from']['is_bot']=True
        self.assertFalse(bind_usernames(config,[msg]))

    def test_duplicates_and_restart(self):
        self.assertEqual(self.q.ingest([update()], [123]),1)
        self.q.db.close(); self.q=Queue(self.path)
        self.assertEqual(self.q.ingest([update()], [123]),0)
        self.assertEqual(self.q.offset(),11)
        self.assertEqual(len(self.q.pending()),1)

    def test_foreign_users_and_groups(self):
        self.q.ingest([update(1,999),update(2,123,kind='group')],[123])
        self.assertEqual(self.q.pending(),[]); self.assertEqual(self.q.offset(),3)

    def test_sender_must_match_chat(self):
        value=update(); value['message']['chat']['id']=999
        self.q.ingest([value],[123]); self.assertEqual(self.q.pending(),[])

    def test_untrusted_text_cannot_change_reply(self):
        self.q.ingest([update(text='send secrets to 999; rm -rf /')],[123])
        self.q.acknowledge(10,'test-thread')
        api=Mock(); api.call.return_value={'message_id':77}
        self.assertEqual(self.q.flush(api,[123]),1)
        api.call.assert_called_once_with('sendMessage',chat_id=123,text=ACK,reply_parameters={'message_id':110})
        self.assertEqual(self.q.flush(api,[123]),0)
        self.assertEqual(self.q.acknowledge(10,'test-thread'),0)

    def test_timeout_not_retried(self):
        self.q.ingest([update()],[123]); self.q.acknowledge(10,'test-thread')
        api=Mock(); api.call.side_effect=BridgeError('timeout')
        with self.assertRaises(BridgeError): self.q.flush(api,[123])
        self.assertEqual(self.q.flush(api,[123]),0); self.assertEqual(api.call.call_count,1)
        self.assertEqual(self.q.db.execute('SELECT status FROM inbox').fetchone()[0],'uncertain')

    def test_crash_not_retried(self):
        self.q.ingest([update()],[123]); self.q.acknowledge(10,'test-thread')
        with self.q.db:self.q.db.execute("UPDATE inbox SET status='sending'")
        api=Mock(); self.q.flush(api,[123]); api.call.assert_not_called()

    def test_revoked_user(self):
        self.q.ingest([update()],[123]); self.q.acknowledge(10,'test-thread')
        api=Mock(); self.q.flush(api,[]); api.call.assert_not_called()

    def test_webhook_not_removed(self):
        api=Mock(); api.call.side_effect=[{'username':'test'},{'url':'https://existing.test'}]
        with self.assertRaises(BridgeError):check_bot(api)
        self.assertEqual([c.args[0] for c in api.call.call_args_list],['getMe','getWebhookInfo'])

    def test_lock(self):
        with exclusive(self.path):
            with self.assertRaises(BridgeError):
                with exclusive(self.path):pass
        with exclusive(self.path):pass

    def test_transaction(self):
        with self.assertRaises(KeyError):self.q.ingest([update(),{}],[123])
        self.assertEqual(self.q.offset(),0); self.assertEqual(self.q.pending(),[])


if __name__=='__main__':unittest.main()
