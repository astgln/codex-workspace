import json
from pathlib import Path
import tempfile
import unittest
from bridge import BridgeError
from rollout_response import recover

T='11111111-1111-1111-1111-111111111111'
S='22222222-2222-2222-2222-222222222222'
U='33333333-3333-3333-3333-333333333333'
V='44444444-4444-4444-4444-444444444444'
M='workspace-request:-2:abcdef'

class RolloutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'session.jsonl'
    def item(self,item,turn=U):return {'type':'event_msg','payload':{'type':'item_completed','thread_id':T,'turn_id':turn,'item':item}}
    def records(self):return [
        {'type':'session_meta','payload':{'id':T}},
        self.item({'type':'FunctionCallOutput','namespace':'codex_app','name':'send_message_to_thread','output':f'<codex_delegation>\n  <source_thread_id>{S}</source_thread_id>\n  <input>Workspace request: {M}\nRequest</input>\n</codex_delegation>'}),
        self.item({'type':'AgentMessage','id':'answer','phase':'final_answer','content':[{'type':'Text','text':'Public answer'}]}),
        {'type':'event_msg','payload':{'type':'task_complete','turn_id':U}}]
    def run_records(self,rows):
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in rows));return recover(self.path,T,M,S,U)
    def test_exact_reply_excludes_private_and_old_items(self):
        rows=self.records();rows.insert(2,self.item({'type':'Reasoning','raw_content':'SECRET'}));rows.insert(2,self.item({'type':'AgentMessage','id':'old','phase':'final_answer','content':[{'type':'Text','text':'OLD'}]},V))
        self.assertEqual(self.run_records(rows)['events'],[{'type':'agent_message','text':'Public answer'}])
    def test_unfinished_or_missing_marker_returns_none(self):
        self.assertIsNone(self.run_records(self.records()[:-1]));self.assertIsNone(self.run_records(self.records()[:1]+self.records()[2:]))
    def test_wrong_source_is_not_a_match(self):
        rows=self.records();rows[1]['payload']['item']['output']=rows[1]['payload']['item']['output'].replace(S,V)
        self.assertIsNone(self.run_records(rows))
    def test_quoted_marker_in_arbitrary_tool_output_is_not_delivery(self):
        rows=self.records();rows[1]['payload']['item']['name']='exec_command'
        self.assertIsNone(self.run_records(rows))
    def test_duplicate_marker_and_wrong_turn_fail_closed(self):
        rows=self.records();extra=self.records()[1];extra['payload']['turn_id']=V
        with self.assertRaises(BridgeError):self.run_records(rows+[extra])
        rows=self.records();rows[1]['payload']['turn_id']=V
        with self.assertRaises(BridgeError):self.run_records(rows)
    def test_wrong_session_and_symlink_rejected(self):
        rows=self.records();rows[0]['payload']['id']=V
        with self.assertRaises(BridgeError):self.run_records(rows)
        self.run_records(self.records());link=self.path.parent/'link';link.symlink_to(self.path)
        with self.assertRaises(BridgeError):recover(link,T,M,S,U)
