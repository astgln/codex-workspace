import json
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from codex_workspace.agent.worker_dispatch import dispatch_one
from codex_workspace.agent.local_queue import Queue

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
        with patch('codex_workspace.agent.worker_dispatch.snapshot',return_value=self.state),patch('codex_workspace.agent.worker_dispatch.command',return_value=['codex','exec','resume',T,'-']):
            return dispatch_one(self.q,self.home,Path('/codex'),self.catalog,run or self.run_cli,api=self.api)

    def check_unavailable_recovery(self, journal_text=None):
        self.q.receive({'id':-2,'thread':U,'text':'old uncertain request','snapshot':'b'*64})
        self.q.receive({'id':-3,'thread':U,'text':'later same task','snapshot':'c'*64})
        old={'thread':U,'baseline':T,'marker':'old-marker','transport':'cli','prompt':'old uncertain request'}
        with self.q.db:
            self.q.db.execute("UPDATE requests SET status='dispatching',dispatch=? WHERE id=-2",(json.dumps(old),))
            self.q.db.execute("UPDATE requests SET status='pending' WHERE id=-3")
        if journal_text is not None:
            (self.path.parent/f'rollout-test-{U}.jsonl').write_text(journal_text)
        self.assertEqual(self.dispatch()['status'],'completed')
        self.assertEqual(self.calls,1)
        self.assertEqual(self.dispatch(),{'status':'needs_reconciliation','ids':[-2]})
        self.assertEqual(self.calls,1)
        row=self.q.db.execute('SELECT * FROM requests WHERE id=-2').fetchone()
        self.assertEqual(row['status'],'dispatching')
        self.assertEqual(json.loads(row['dispatch']),old)
        self.assertIsNone(row['result'])
        self.assertEqual(self.q.db.execute('SELECT status FROM requests WHERE id=-3').fetchone()[0],'pending')

    def test_missing_recovery_journal_does_not_block_independent_task(self):
        self.check_unavailable_recovery()

    def test_invalid_recovery_journal_does_not_block_independent_task(self):
        self.check_unavailable_recovery('{not valid JSON}\n')

    def test_aborted_request_is_published_once_without_redispatch(self):
        from codex_workspace.agent.queue_transport import publish_results
        def abort(args, **kwargs):
            self.calls+=1
            with self.path.open('a') as out:
                for payload in (
                    {'type':'item_completed','thread_id':T,'turn_id':V,'item':{'type':'UserMessage','id':'u','content':[{'type':'text','text':kwargs['input']}]}},
                    {'type':'turn_aborted','turn_id':V,'reason':'private detail'}):
                    out.write(json.dumps({'type':'event_msg','payload':payload})+'\n')
            return SimpleNamespace(returncode=1)
        self.assertEqual(self.dispatch(abort)['status'],'completed')
        publish_results(self.q,self.api)
        row=self.q.db.execute('SELECT * FROM requests WHERE id=-1').fetchone()
        self.assertEqual(row['status'],'complete')
        self.assertEqual(json.loads(row['result'])['status'],'failed')
        self.assertNotIn('private detail',row['result'])
        self.assertEqual(self.dispatch()['status'],'idle')
        self.assertEqual(self.calls,1)

    def test_stop_after_preflight_creates_no_dispatch_intent(self):
        with patch('codex_workspace.agent.worker_dispatch.snapshot',return_value=self.state), patch('codex_workspace.agent.worker_dispatch.command',return_value=['codex']):
            result=dispatch_one(self.q,self.home,Path('/codex'),self.catalog,api=self.api,should_stop=lambda:True)
        self.assertEqual(result, {'status':'stopping'})
        self.assertEqual(self.q.pending()['messages'][0]['local_status'], 'pending')
        self.api.call.assert_not_called()

    def test_running_turn_published_before_process_completion(self):
        from codex_workspace.agent.worker_recovery import collect
        from codex_workspace.agent.queue_transport import publish_results
        request=self.q.begin(-1,T,U,api=self.api)
        with self.q.db:
            dispatch={'thread':T,'baseline':U,'marker':request['marker'],'transport':'cli','prompt':request['text']}
            self.q.db.execute('UPDATE requests SET dispatch=? WHERE id=-1',(json.dumps(dispatch),))
        with self.path.open('a') as out:
            out.write(json.dumps({'type':'event_msg','payload':{'type':'item_completed','thread_id':T,'turn_id':V,'item':{'type':'UserMessage','id':'u','content':[{'type':'text','text':request['text']}]}}})+'\n')
        row=self.q.db.execute('SELECT * FROM requests').fetchone()
        self.assertFalse(collect(self.q,self.home,row,include_running=True))
        publish_results(self.q,self.api)
        row=self.q.db.execute('SELECT * FROM requests').fetchone()
        self.assertEqual(row['status'],'dispatched')
        self.assertEqual(json.loads(row['result'])['status'],'running')
        self.assertEqual(json.loads(row['result'])['turn_id'],V)
        revision=row['revision']
        collect(self.q,self.home,row,include_running=True)
        self.assertEqual(self.q.db.execute('SELECT revision FROM requests').fetchone()[0],revision)

    def test_real_child_process_publishes_running_then_completed(self):
        import sys
        from codex_workspace.agent.queue_transport import publish_results
        script=self.home/'fake_cli.py'
        script.write_text("""import json,sys,time
path,thread,turn=sys.argv[1:]
prompt=sys.stdin.read()
def emit(item):
 with open(path,'a') as out:
  out.write(json.dumps({'type':'event_msg','payload':item})+'\\n')
emit({'type':'item_completed','thread_id':thread,'turn_id':turn,'item':{'type':'UserMessage','id':'u','content':[{'type':'text','text':prompt}]}})
time.sleep(5.2)
emit({'type':'item_completed','thread_id':thread,'turn_id':turn,'item':{'type':'AgentMessage','id':'a','phase':'final_answer','content':[{'type':'Text','text':'done'}]}})
emit({'type':'task_complete','turn_id':turn})
""")
        args=[sys.executable,str(script),str(self.path),T,V]
        with patch('codex_workspace.agent.worker_dispatch.snapshot',return_value=self.state),patch('codex_workspace.agent.worker_dispatch.command',return_value=args):
            result=dispatch_one(self.q,self.home,Path('/unused'),self.catalog,api=self.api)
        publish_results(self.q,self.api)
        self.assertEqual(result['status'],'completed')
        responses=[call.args[1] for call in self.api.call.call_args_list if call.args[0]=='/v2/responses']
        self.assertEqual(responses[0]['status'],'running')
        self.assertEqual(responses[-1]['status'],'completed')
        self.assertTrue(all(response['turn_id']==V for response in responses))
        self.assertEqual(self.q.db.execute('SELECT status FROM requests').fetchone()[0],'complete')

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
        from codex_workspace.agent.runtime_support import BridgeError
        with patch('codex_workspace.agent.worker_dispatch.snapshot',side_effect=BridgeError('unsupported settings')):
            result=dispatch_one(self.q,self.home,Path('/codex'),self.catalog,api=self.api)
        self.assertEqual(result,{'status':'waiting_for_tasks','requests':[{'id':-1,'reason':'task_settings_unavailable'}]})
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'pending')
        self.assertEqual(self.calls,0)


    def test_revoked_or_unverifiable_request_never_starts_cli(self):
        from codex_workspace.agent.runtime_support import BridgeError
        for transport in (self.dispatch,):
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
