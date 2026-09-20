import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from history_watch import sync_once

class WatchTests(unittest.TestCase):
 def test_checkpoint_and_pending_idle_refresh(self):
  class API:
   def __init__(self):self.calls=[]
   def call(self,path,data):
    self.calls.append((path,data))
    return {'threads':[{'thread':'task'}]} if path.endswith('/pending') else {}
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'journal';path.write_text(json.dumps({'type':'session_meta','payload':{'id':'task'}})+'\n')
   catalog={'project_id':'project','threads':[{'id':'task','project_id':'project'}]};api=API();cache={}
   with patch('history_watch.locate',return_value=path):
    sync_once(api,catalog,'project',Path(tmp),cache)
    with patch('history_watch.read_public',side_effect=AssertionError('must not rescan idle file')):
     sync_once(api,catalog,'project',Path(tmp),cache)
   self.assertEqual(cache['task']['offset'],path.stat().st_size)
   self.assertEqual(len([p for p,d in api.calls if p.endswith('/publish')]),2)
