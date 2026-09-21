import base64
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from codex_workspace.relay import push
from codex_workspace.relay.store import Store
from codex_workspace.domain import workspace, domain

class PushTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);push.initialize(self.store)
  self.store.mutate(lambda s:s.update(bindings={'owner':1,'friend':2},catalog={'task':{'id':'task'}},thread_grants={'2':['task']}))
  public=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
  encode=lambda data:base64.urlsafe_b64encode(data).decode().rstrip('=')
  self.sub={'endpoint':'https://web.push.apple.com/test','keys':{'p256dh':encode(public),'auth':encode(os.urandom(16))}}
 def tearDown(self):self.temp.cleanup()
 def subscribe(self,uid=1):push.handle(self.store,uid,'owner','subscribe',{'subscription':self.sub})
 def test_validation_and_ownership(self):
  for endpoint in ('http://web.push.apple.com/a','https://127.0.0.1/a','https://web.push.apple.com.evil/a','https://web.push.apple.com:444/a','https://user@web.push.apple.com/a'):
   self.assertFalse(push.endpoint_ok(endpoint))
  self.subscribe()
  with self.assertRaises(workspace.Forbidden):self.subscribe(2)
  with self.assertRaises(workspace.Forbidden):push.handle(self.store,99,'owner','config',{})
  self.assertEqual(len(base64.urlsafe_b64decode(push.public_key(self.store)+'=')),65)
 def test_approval_only_owner_and_durable_dedup(self):
  self.subscribe();now=int(time.time())
  self.store.mutate(lambda s:s['items'].update({'-1':{'id':-1,'channel':'web','thread':'task','status':'awaiting_approval','expires':now+100,'created':now}}))
  with patch('codex_workspace.relay.push.send',return_value=201) as send:
   push.tick(self.store,'owner');push.tick(self.store,'owner');self.assertEqual(send.call_count,1)
   self.assertNotIn('task',send.call_args.args[2]['body'])
 def test_member_receives_answer_but_not_approval(self):
  self.subscribe(2);now=int(time.time())
  self.store.mutate(lambda s:s['items'].update({'-1':{'id':-1,'channel':'web','thread':'task','status':'awaiting_approval','expires':now+100,'created':now}}))
  with push.database(self.store) as db:db.execute('INSERT INTO push_answers VALUES(?,?,?)',('answer','task',now))
  with patch('codex_workspace.relay.push.send',return_value=201) as send:
   push.tick(self.store,'owner');self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[2]['body'],'Готов новый ответ')
 def test_revoked_grants_old_answers_and_dead_subscription(self):
  self.subscribe(2);now=int(time.time())
  with push.database(self.store) as db:
   db.execute('INSERT INTO push_answers VALUES(?,?,?)',('old','task',now-20))
   db.execute('INSERT INTO push_answers VALUES(?,?,?)',('new','task',now))
  self.store.mutate(lambda s:s['thread_grants'].update({'2':[]}))
  with patch('codex_workspace.relay.push.send',return_value=410) as send:
   push.tick(self.store,'owner');send.assert_not_called()
   self.store.mutate(lambda s:s['thread_grants'].update({'2':['task']}))
   push.tick(self.store,'owner');self.assertEqual(send.call_count,1)
  with push.database(self.store) as db:self.assertEqual(db.execute('SELECT count(*) FROM push_subscriptions').fetchone()[0],0)
 def test_retry_is_delayed(self):
  self.subscribe();now=int(time.time())
  with push.database(self.store) as db:db.execute('INSERT INTO push_answers VALUES(?,?,?)',('answer','task',now))
  with patch('codex_workspace.relay.push.send',return_value=503) as send:
   push.tick(self.store,'owner');push.tick(self.store,'owner');self.assertEqual(send.call_count,1)
 def test_real_encryption_and_vapid_signing_without_network(self):
  import requests
  response=requests.Response();response.status_code=201
  with patch.dict('os.environ',{'PUBLIC_ORIGIN':'https://workspace.example'}),patch.object(push.NoRedirect,'request',return_value=response) as request:
   self.assertEqual(push.send(self.store,self.sub,{'body':'Готов новый ответ'}),201)
   headers=request.call_args.kwargs['headers']
   self.assertIn('vapid',headers['authorization'].lower())
   self.assertEqual(headers['content-encoding'],'aes128gcm')
 def test_same_turn_from_history_and_request_sends_once(self):
  self.subscribe();now=int(time.time())
  self.store.mutate(lambda s:s['items'].update({'-1':{'id':-1,'channel':'web','thread':'task','status':'delivered','created':now,'result_status':'completed','result_turn_id':'turn-1','result_updated':now}}))
  from codex_workspace.relay import history
  history.handle(self.store,None,'owner','publish',{'thread':'task','messages':[{'id':'message-1','position':'1','role':'assistant','text':'reply','created':now,'phase':'final_answer','turn_id':'turn-1'}]},collector=True)
  with patch('codex_workspace.relay.push.send',return_value=201) as send:
   push.tick(self.store,'owner');push.tick(self.store,'owner')
   self.assertEqual(send.call_count,1)
 def test_uncertain_network_result_is_not_retried(self):
  self.subscribe();now=int(time.time())
  with push.database(self.store) as db:db.execute('INSERT INTO push_answers VALUES(?,?,?)',('answer','task',now))
  with patch('codex_workspace.relay.push.send',return_value=None) as send:
   push.tick(self.store,'owner')
   with push.database(self.store) as db:db.execute('UPDATE push_deliveries SET next_attempt=?',(now-1,))
   push.tick(self.store,'owner')
   self.assertEqual(send.call_count,1)
  with push.database(self.store) as db:self.assertEqual(db.execute('SELECT done FROM push_deliveries').fetchone()[0],2)
 def test_crash_after_send_intent_is_not_retried(self):
  self.subscribe();now=int(time.time())
  with push.database(self.store) as db:db.execute('INSERT INTO push_answers VALUES(?,?,?)',('answer','task',now))
  with patch('codex_workspace.relay.push.send',side_effect=RuntimeError('crash')):
   with self.assertRaises(RuntimeError):push.tick(self.store,'owner')
  with push.database(self.store) as db:db.execute('UPDATE push_deliveries SET next_attempt=?',(now-1,))
  with patch('codex_workspace.relay.push.send') as send:
   push.tick(self.store,'owner');send.assert_not_called()
 def test_approval_preview_includes_task_and_request(self):
  self.subscribe();now=int(time.time())
  def seed(s):
   s['catalog']['task']['title']='Launcher'
   s['items']['-1']={'id':-1,'channel':'web','thread':'task','text':'Проверь подключение','status':'awaiting_approval','expires':now+100,'created':now}
  self.store.mutate(seed)
  with patch('codex_workspace.relay.push.send',return_value=201) as send:
   push.tick(self.store,'owner')
   payload=send.call_args.args[2]
   self.assertEqual(payload['title'],'Launcher')
   self.assertEqual(payload['body'],'На одобрение: Проверь подключение')
   self.assertEqual(payload['url'],'/#approvals')
 def test_history_preview_uses_exact_answer_not_latest_message(self):
  self.subscribe(2);now=int(time.time())
  from codex_workspace.relay import history
  history.handle(self.store,None,'owner','publish',{'thread':'task','messages':[
   {'id':'final','position':'1','role':'assistant','text':'Точный ответ','created':now,'phase':'final_answer','turn_id':'turn-1'},
   {'id':'later','position':'2','role':'assistant','text':'Другое рассуждение','created':now,'phase':'commentary','turn_id':'turn-2'}]},collector=True)
  with patch('codex_workspace.relay.push.send',return_value=201) as send:
   push.tick(self.store,'owner')
   self.assertEqual(send.call_args.args[2]['body'],'Точный ответ')
 def test_request_preview_and_unicode_payload_budget(self):
  self.subscribe();now=int(time.time())
  def seed(s):
   s['catalog']['task']['title']='😀'*200
   s['items']['-1']={'id':-1,'channel':'web','thread':'task','status':'delivered','result_status':'completed','result_turn_id':'turn','result_updated':now,'events':[{'type':'agent_message','text':'earlier'},{'type':'agent_message','text':'😀'*4000}]}
  self.store.mutate(seed)
  with patch('codex_workspace.relay.push.send',return_value=201) as send:
   push.tick(self.store,'owner')
   payload=send.call_args.args[2]
   self.assertTrue(payload['body'].endswith('…'))
   self.assertEqual(len(payload['body']),500)
   self.assertLess(len(json.dumps(payload,ensure_ascii=False).encode()),3500)
 def test_preview_redacts_known_credentials(self):
  from codex_workspace.relay.push_preview import preview
  self.assertNotIn('sk-'+'a'*30,preview('Ответ sk-'+'a'*30))
  self.assertEqual(preview('API_KEY=private\nГотово'),'API_KEY=[hidden] Готово')
