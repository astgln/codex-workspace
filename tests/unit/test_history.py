import tempfile
import unittest
from codex_workspace.domain import workspace
from codex_workspace.relay import history
from codex_workspace.relay.store import Store
from codex_workspace.agent.history_client import messages


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        def setup(s):
            s['bindings']={'owner':10,'friend':20}
            s['catalog']={'shared-thread':{'id':'shared-thread','title':'Shared'},'private-thread':{'id':'private-thread','title':'Private'}}
            s['thread_grants']={'20':['shared-thread']}
        self.store.mutate(setup)

    def tearDown(self):self.temp.cleanup()

    def call(self,action,body,uid=20,collector=False):return history.handle(self.store,uid,'owner',action,body,collector)

    def test_shared_history_pagination_and_revocation(self):
        self.call('read',{'thread':'shared-thread'})
        self.assertEqual(len(self.call('pending',{},None,True)['threads']),1)
        batch=[{'id':str(i),'position':f'{i:05d}','created':i,'role':'assistant','text':'public'} for i in range(60)]
        self.call('publish',{'thread':'shared-thread','messages':batch,'finish':True,'mode':'latest','cursor':None,'more':False},None,True)
        first=self.call('read',{'thread':'shared-thread'})
        self.assertEqual(len(first['messages']),50)
        second=self.call('read',{'thread':'shared-thread','before':first['before']})
        self.assertEqual(len(second['messages']),10)
        self.store.mutate(lambda s:s['thread_grants'].update({'20':[]}))
        with self.assertRaises(workspace.Forbidden):self.call('read',{'thread':'shared-thread'})

    def test_browser_cannot_publish_or_read_private_history(self):
        with self.assertRaises(workspace.Forbidden):self.call('publish',{'thread':'shared-thread','messages':[]})
        with self.assertRaises(workspace.Forbidden):self.call('read',{'thread':'private-thread'})
        with self.assertRaises(workspace.Forbidden):self.call('publish',{'thread':'unknown','messages':[]},None,True)

    def test_extractor_omits_tools_reasoning_and_masks_tokens(self):
        result=messages({'turns':[{'id':'turn','startedAt':1000,'items':[
            {'id':'u','type':'userMessage','content':[{'type':'text','text':'TOKEN=private\nHello'}]},
            {'type':'reasoning','text':'hidden'},{'type':'commandExecution','output':'hidden'},
            {'id':'a','type':'agentMessage','phase':'final_answer','text':'Answer'}]}]})
        self.assertEqual([m['role'] for m in result],['user','assistant'])
        self.assertEqual(result[0]['text'],'TOKEN=[hidden]\nHello')
        self.assertNotIn('private',str(result))

    def test_bridge_envelopes_are_not_duplicated_as_history(self):
        self.assertEqual([m['text'] for m in messages({'turns':[{'id':'turn','startedAt':1000,'items':[
            {'type':'userMessage','content':[{'type':'text','text':'Workspace request: marker\nrequest'}]},
            {'type':'agentMessage','phase':'final_answer','text':'reply'}]}]})],['reply'])


if __name__=='__main__':unittest.main()
