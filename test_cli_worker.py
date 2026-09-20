import json
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from worker_dispatch import dispatch_one
from legacy_shared_worker import dispatch_shared
from web_client import Queue

T='11111111-1111-1111-1111-111111111111'
U='22222222-2222-2222-2222-222222222222'
V='33333333-3333-3333-3333-333333333333'


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.api=Mock();self.api.call.return_value={"allowed":True}
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.home=Path(temp.name);self.q=Queue(self.home);self.addCleanup(self.q.db.close)
        self.q.receive({'id':-1,'thread':T,'text':'$(touch SHOULD_NOT_EXIST)','snapshot':'a'*64})
        with self.q.db:self.q.db.execute("UPDATE requests SET status='pending'")
        folder=self.home/'sessions/2026/09/21';folder.mkdir(parents=True)
        self.path=folder/f'rollout-test-{T}.jsonl'
        self.path.write_text(json.dumps({'type':'session_meta','payload':{'id':T}})+'\n')
        with self.path.open('a') as out:
            out.write(json.dumps({'type':'event_msg','payload':{'type':'task_complete','turn_id':U}})+'\n')
        self.catalog={'threads':[{'id':T}]}
        self.state={'status':'ready','baseline':U,'thread':T,'settings':{'cwd':str(self.home)}}
        self.calls=0

    def run_cli(self,args,**kwargs):
        self.calls+=1
        self.assertEqual(kwargs['input'].count('$(touch SHOULD_NOT_EXIST)'),1)
        self.assertEqual(kwargs['input'],'$(touch SHOULD_NOT_EXIST)')
        self.assertNotIn('shell',kwargs)
        with self.path.open('a') as out:
            for payload in [
                {'type':'item_completed','thread_id':T,'turn_id':V,'item':{'type':'UserMessage','id':'u','content':[{'type':'text','text':kwargs['input']}]}},
                {'type':'item_completed','thread_id':T,'turn_id':V,'item':{'type':'AgentMessage','id':'a','phase':'final_answer','content':[{'type':'Text','text':'reply'}]}},
                {'type':'task_complete','turn_id':V}]:
                out.write(json.dumps({'type':'event_msg','payload':payload})+'\n')
        return SimpleNamespace(returncode=0)

    def dispatch(self,run=None):
        with patch('worker_dispatch.snapshot',return_value=self.state),patch('worker_dispatch.command',return_value=['codex','exec','resume',T,'-']):
            return dispatch_one(self.q,self.home,Path('/codex'),self.catalog,run or self.run_cli,api=self.api)

    def test_stop_after_preflight_creates_no_dispatch_intent(self):
        with patch('worker_dispatch.snapshot',return_value=self.state), patch('worker_dispatch.command',return_value=['codex']):
            result=dispatch_one(self.q,self.home,Path('/codex'),self.catalog,api=self.api,should_stop=lambda:True)
        self.assertEqual(result, {'status':'stopping'})
        self.assertEqual(self.q.pending()['messages'][0]['local_status'], 'pending')
        self.api.call.assert_not_called()

    def test_success_is_correlated_and_not_repeated(self):
        self.assertEqual(self.dispatch()['status'],'completed')
        self.assertEqual(self.dispatch()['status'],'idle')
        self.assertEqual(self.calls,1)
        row=self.q.db.execute('SELECT * FROM requests').fetchone()
        self.assertEqual(row['status'],'publishing')
        self.assertEqual(json.loads(row['result'])['events'],[{'type':'agent_message','text':'reply'}])

    def test_interrupted_dispatch_is_never_retried(self):
        def crash(*a,**kw):raise OSError('lost process')
        with self.assertRaises(OSError):self.dispatch(crash)
        self.assertEqual(self.dispatch()['status'],'needs_reconciliation')
        self.assertEqual(self.calls,0)
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'dispatching')

    def test_busy_and_read_only_tasks_stay_pending(self):
        self.state={'status':'busy'}
        self.assertEqual(self.dispatch(),{'status':'waiting_for_tasks','requests':[{'id':-1,'reason':'desktop_writer_lock'}]})
        self.catalog['threads'][0]['read_only']=True
        self.assertEqual(self.dispatch()['status'],'idle')
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'pending')

    def test_invalid_settings_remain_pending_without_dispatch_intent(self):
        from bridge import BridgeError
        with patch('worker_dispatch.snapshot',side_effect=BridgeError('unsupported settings')):
            result=dispatch_one(self.q,self.home,Path('/codex'),self.catalog,api=self.api)
        self.assertEqual(result,{'status':'waiting_for_tasks','requests':[{'id':-1,'reason':'task_settings_unavailable'}]})
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'pending')
        self.assertEqual(self.calls,0)

    def shared(self, *, active=False, fail=False, slow=False):
        owner=self
        class Client:
            def __init__(self,socket):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*exc):pass
            async def call(self,method,params):
                if method in ('thread/read','thread/resume'):
                    return {'thread':{'status':{'type':'active' if active else 'idle'}}}
                if method=='turn/start':
                    if fail:raise OSError('connection lost')
                    if not slow:owner.run_cli([],input=params['input'][0]['text'])
                    return {'turn':{'id':V}}
                raise AssertionError(method)
            async def wait_completed(self,thread,turn):
                owner.assertEqual((thread,turn),(T,V))
                if slow:raise TimeoutError()
                return {'id':V,'status':'completed'}
        with patch('legacy_shared_worker.snapshot',return_value=self.state):
            return asyncio.run(dispatch_shared(self.q,self.home,self.home/'socket',self.catalog,Client,api=self.api))

    def test_shared_delivers_plain_text_and_pins_turn(self):
        self.assertEqual(self.shared()['status'],'completed')
        row=self.q.db.execute('SELECT * FROM requests').fetchone()
        self.assertEqual(json.loads(row['dispatch'])['turn_id'],V)
        self.assertEqual(json.loads(row['dispatch'])['transport'],'shared')
        self.assertEqual(self.shared()['status'],'idle')
        self.assertEqual(self.calls,1)

    def test_shared_does_not_interrupt_active_task(self):
        self.assertEqual(self.shared(active=True)['status'],'waiting_for_tasks')
        self.assertEqual(self.calls,0)
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'pending')

    def test_shared_disconnect_leaves_intent_without_resending(self):
        with self.assertRaises(OSError):self.shared(fail=True)
        self.assertEqual(self.shared()['status'],'needs_reconciliation')
        self.assertEqual(self.calls,0)

    def test_shared_slow_turn_is_collected_later_without_resubmitting(self):
        self.assertEqual(self.shared(slow=True), {'status':'awaiting_completion','id':-1})
        row=self.q.db.execute('SELECT * FROM requests').fetchone()
        self.assertEqual(row['status'],'dispatched')
        self.assertEqual(json.loads(row['dispatch'])['turn_id'],V)
        self.assertEqual(self.shared()['status'],'needs_reconciliation')
        self.assertEqual(self.calls,0)
        self.run_cli([],input='$(touch SHOULD_NOT_EXIST)')
        self.assertEqual(self.shared()['status'],'idle')
        row=self.q.db.execute('SELECT * FROM requests').fetchone()
        self.assertEqual(row['status'],'publishing')
        self.assertEqual(json.loads(row['result'])['events'],[{'type':'agent_message','text':'reply'}])
        self.assertEqual(self.calls,1)

    def test_revoked_or_unverifiable_request_never_starts_cli_or_shared_turn(self):
        from bridge import BridgeError
        for transport in (self.dispatch,self.shared):
            for response in ({'allowed':False},{},{'allowed':'true'}):
                with self.subTest(transport=transport.__name__,response=response):
                    self.api.call.return_value=response
                    with self.assertRaises(BridgeError):transport()
                    self.assertEqual(self.calls,0)
                    self.assertEqual(self.q.pending()['messages'][0]['local_status'],'pending')
            self.api.call.side_effect=OSError('offline')
            with self.assertRaises(OSError):transport()
            self.assertEqual(self.calls,0)
            self.api.call.side_effect=None
