import json
import tempfile
import unittest
from pathlib import Path
from codex_workspace.codex.rollout_history import read_public
from codex_workspace.agent.history_client import messages, publish
from codex_workspace.agent.runtime_support import BridgeError

class HistoryJournalTests(unittest.TestCase):
 def test_only_public_completed_items_even_after_tools(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'log';rows=[{'type':'session_meta','payload':{'id':'task','base_instructions':'SECRET'}}]
   def item(turn,kind,**kw):return {'timestamp':'2026-09-20T01:00:00Z','type':'event_msg','payload':{'type':'item_completed','thread_id':'task','turn_id':turn,'item':{'type':kind,**kw}}}
   rows.extend([item('a','UserMessage',id='u',content=[{'type':'text','text':'Question'}]),item('a','AgentMessage',id='a',phase='final_answer',content=[{'type':'Text','text':'Answer'}]),item('a','Reasoning',raw_content='SECRET'),item('a','CommandExecution',stdout='SECRET'),item('b','FunctionCallOutput',namespace='codex_app',name='send_message_to_thread',output='SECRET'),item('b','AgentMessage',id='b',phase='final_answer',content=[{'type':'Text','text':'Duplicate'}]),item('c','UserMessage',id='c',content=[{'type':'text','text':'<codex_internal_context>SECRET'}])])
   path.write_text('\n'.join(json.dumps(r) for r in rows))
   self.assertEqual([m['text'] for m in messages(read_public(path,'task'))],['Question','Answer','Duplicate'])
   with self.assertRaises(BridgeError):read_public(path,'other')
 def test_batches_never_exceed_api_count_limit(self):
  class API:
   def __init__(self):self.calls=[]
   def call(self,path,data):self.calls.append(data)
  api=API();read={'thread':{'id':'task'},'turns':[{'id':'turn','startedAt':1,'items':[{'id':str(i),'type':'agentMessage','phase':'final_answer','text':'x'} for i in range(201)]}]}
  publish(api,read,'latest');self.assertEqual([len(c['messages']) for c in api.calls],[100,100,1,0])

 def test_incremental_active_turn_and_partial_tail(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'log'
   def row(kind,text,ident,stamp):return json.dumps({'type':'event_msg','timestamp':stamp,'payload':{'type':'item_completed','thread_id':'task','turn_id':'active','item':{'type':kind,'id':ident,'phase':'commentary','content':[{'type':'text','text':text}]}}})+'\n'
   path.write_text(json.dumps({'type':'session_meta','payload':{'id':'task'}})+'\n'+row('UserMessage','<heartbeat>private','u','2026-09-20T01:00:00Z')+row('AgentMessage','Visible continuation','a','2026-09-20T02:00:00Z'))
   first=read_public(path,'task');self.assertEqual([m['text'] for m in messages(first)],['Visible continuation'])
   tail=row('AgentMessage','Later answer','b','2026-09-20T03:00:00Z')
   with path.open('a') as stream:stream.write(tail[:30])
   partial=read_public(path,'task',first['source_offset']);self.assertEqual(partial['source_offset'],first['source_offset'])
   with path.open('a') as stream:stream.write(tail[30:])
   last=messages(read_public(path,'task',partial['source_offset']))
   full=messages(read_public(path,'task'))
   self.assertEqual(last,[full[-1]]);self.assertEqual(last[0]['created']-full[0]['created'],3600)
