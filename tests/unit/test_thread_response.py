import unittest
from codex_workspace.agent.runtime_support import BridgeError
from codex_workspace.codex.thread_response import correlate, prompt_prefix


class ResponseCorrelationTests(unittest.TestCase):
    def read(self, **changes):
        turn={'id':'new-turn','status':'completed','items':[
            {'type':'userMessage','content':[{'type':'text','text':prompt_prefix('marker')+'Approved request'}]},
            {'type':'reasoning','text':'Never export'},
            {'type':'commandExecution','output':'Never export'},
            {'type':'agentMessage','phase':'commentary','text':'Intermediate'},
            {'type':'agentMessage','phase':'final_answer','text':'Actual response'}]}
        turn.update(changes)
        return {'thread':{'id':'target'},'turns':[turn]}

    def get(self, read):
        return correlate(read,'target','marker','baseline')

    def test_only_exact_new_turn_final_reply(self):
        read=self.read()
        read['turns'].insert(0,{'id':'other','status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':'Unrelated history'}]})
        result=self.get(read)
        self.assertEqual(result['turn_id'],'new-turn')
        self.assertEqual(result['events'],[{'type':'agent_message','text':'Actual response'}])

    def test_empty_or_old_turn_never_supplies_reply(self):
        for read in (self.read(items=[]),self.read(id='baseline'),self.read(items=[{'type':'agentMessage','phase':'final_answer','text':'Unrelated'}])):
            self.assertIsNone(self.get(read))

    def test_marker_in_quoted_text_is_not_dispatch(self):
        read=self.read()
        read['turns'][0]['items'][0]['content'][0]['text']='Quoted: '+prompt_prefix('marker')
        self.assertIsNone(self.get(read))

    def test_different_target_or_duplicate_marker_fails(self):
        read=self.read();read['thread']['id']='other'
        with self.assertRaises(BridgeError):self.get(read)
        read=self.read();read['turns'].append({**read['turns'][0],'id':'duplicate'})
        with self.assertRaises(BridgeError):self.get(read)

    def test_completed_without_final_is_not_success(self):
        read=self.read();read['turns'][0]['items'].pop()
        self.assertIsNone(self.get(read))

    def test_failure_does_not_export_raw_error(self):
        result=self.get(self.read(status='failed',error={'message':'secret in tool failure'}))
        self.assertEqual(result['status'],'failed')
        self.assertNotIn('secret',str(result))


if __name__=='__main__':unittest.main()
