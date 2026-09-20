import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cli_worker import dispatch_one
from web_client import Queue

T='11111111-1111-1111-1111-111111111111'
U='22222222-2222-2222-2222-222222222222'
V='33333333-3333-3333-3333-333333333333'


class WorkerTests(unittest.TestCase):
    def setUp(self):
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
        with patch('cli_worker.snapshot',return_value=self.state),patch('cli_worker.command',return_value=['codex','exec','resume',T,'-']):
            return dispatch_one(self.q,self.home,Path('/codex'),self.catalog,run or self.run_cli)

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
        self.assertEqual(self.dispatch()['status'],'idle')
        self.catalog['threads'][0]['read_only']=True
        self.assertEqual(self.dispatch()['status'],'idle')
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'pending')
