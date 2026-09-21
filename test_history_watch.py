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
   with patch('history_sync.locate',return_value=path):
    sync_once(api,catalog,'project',Path(tmp),cache)
    with patch('history_sync.read_public',side_effect=AssertionError('must not rescan idle file')):
     sync_once(api,catalog,'project',Path(tmp),cache)
   self.assertEqual(cache['task']['offset'],path.stat().st_size)
   self.assertEqual(len([p for p,d in api.calls if p.endswith('/publish')]),2)
 def test_explicit_multiple_projects_only(self):
  class API:
   def call(self,path,data):return {'threads':[]}
  from bridge import BridgeError
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'journal';path.write_text(json.dumps({'type':'session_meta','payload':{'id':'task'}})+'\n')
   catalog={'project_id':'installation','projects':[{'id':'other'}],'threads':[{'id':'task','project_id':'other'}]}
   with patch('history_sync.locate',return_value=path):
    sync_once(API(),catalog,'installation',Path(tmp),{})
    catalog['threads'][0]['project_id']='not-authorized'
    with self.assertRaises(BridgeError):sync_once(API(),catalog,'installation',Path(tmp),{})

 def test_reader_version_change_replays_without_advancing_on_failure(self):
  class API:
   def call(self,path,data):return {'threads':[]}
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'journal';path.write_text(json.dumps({'type':'session_meta','payload':{'id':'task'}})+'\n')
   stat=path.stat()
   catalog={'project_id':'project','threads':[{'id':'task','project_id':'project'}]}
   stale={'checkpoint_version':1,'reader_version':0,'file':[stat.st_dev,stat.st_ino],'offset':stat.st_size}
   cache={'task':stale.copy()}
   with patch('history_sync.locate',return_value=path), patch('history_sync.publish',side_effect=OSError('offline')):
    failures={}
    sync_once(API(),catalog,'project',Path(tmp),cache,failures)
    self.assertEqual(failures,{'task':'history_unavailable'})
   self.assertEqual(cache['task'],stale)
   from rollout_history import read_public, READER_VERSION
   with patch('history_sync.locate',return_value=path), patch('history_sync.read_public',wraps=read_public) as reader:
    sync_once(API(),catalog,'project',Path(tmp),cache)
   reader.assert_called_once_with(path,'task',0)
   self.assertEqual(cache['task']['reader_version'],READER_VERSION)

 def test_missing_journal_does_not_starve_other_tasks(self):
  class API:
   def call(self,path,data):return {'threads':[]}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);good=root/'good'
   good.write_text(json.dumps({'type':'session_meta','payload':{'id':'good'}})+'\n')
   catalog={'project_id':'project','threads':[{'id':name,'project_id':'project'} for name in ('missing','good')]}
   cache={};failures={}
   with patch('history_sync.locate',side_effect=lambda root,ident:root/ident):
    sync_once(API(),catalog,'project',root,cache,failures)
   self.assertEqual(failures,{'missing':'history_unavailable'})
   self.assertIn('good',cache);self.assertNotIn('missing',cache)

 def test_quota_retry_keeps_committed_history_cursor(self):
  class API:
   failing=True
   def call(self,path,data):
    if path=='/v2/usage' and self.failing:raise OSError('offline')
    return {'threads':[]}
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'journal';path.write_text('synthetic fixture')
   catalog={'project_id':'project','threads':[{'id':'task','project_id':'project'}]}
   cache={};failures={};api=API()
   read={'thread':{'id':'task'},'turns':[],'source_offset':path.stat().st_size,
         'weekly_quota':{'used_percent':12,'resets_at':9999,'observed_at':100}}
   with patch('history_sync.locate',return_value=path),patch('history_sync.read_public',return_value=read),patch('history_sync.publish') as publish:
    sync_once(api,catalog,'project',Path(tmp),cache,failures)
    self.assertEqual(failures,{'task':'quota_unavailable'})
    self.assertEqual(cache['task']['offset'],path.stat().st_size)
    self.assertIn('pending_quota',cache['task'])
    api.failing=False
    with patch('history_sync.read_public',side_effect=AssertionError('no replay')):
     sync_once(api,catalog,'project',Path(tmp),cache,{})
    self.assertNotIn('pending_quota',cache['task'])
    self.assertEqual(publish.call_count,1)

 def test_manual_sync_validates_full_scope_before_any_publication(self):
  from history_client import sync_catalog
  from bridge import BridgeError
  from unittest.mock import Mock
  api=Mock()
  catalog={'project_id':'project','threads':[
   {'id':'good','project_id':'project'},
   {'id':'bad','project_id':'different-project'}]}
  with self.assertRaises(BridgeError):
   sync_catalog(api,catalog,'project',Path('/unused'))
  api.call.assert_not_called()

 def test_manual_sync_preserves_good_tasks_after_missing_journal(self):
  from history_client import sync_catalog
  class API:
   def call(self,path,data):return {'threads':[]}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   (root/'good').write_text(json.dumps({'type':'session_meta','payload':{'id':'good'}})+'\n')
   catalog={'project_id':'project','threads':[{'id':name,'project_id':'project'} for name in ('missing','good')]}
   with patch('history_sync.locate',side_effect=lambda root,ident:root/ident),patch('history_sync.publish') as publish:
    result=sync_catalog(API(),catalog,'project',root)
   self.assertEqual(result,{'messages':0,'failed_tasks':1,'failed_services':[]})
   publish.assert_called_once()

 def test_pending_failure_does_not_starve_history_or_quota(self):
  class API:
   def __init__(self,response):self.response=response;self.calls=[]
   def call(self,path,data):
    self.calls.append(path)
    if path.endswith('/pending'):
     if isinstance(self.response,Exception):raise self.response
     return self.response
    return {}
  for response in (OSError('offline'),None,{'threads':None},{'threads':[{}]}):
   with self.subTest(response=type(response).__name__), tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);path=root/'task';path.write_text('fixture')
    catalog={'project_id':'project','threads':[{'id':'task','project_id':'project'}]}
    quota={'used_percent':12,'resets_at':9999,'observed_at':100}
    cache={};failures={};services={};api=API(response)
    read={'thread':{'id':'task'},'turns':[],'source_offset':path.stat().st_size,'weekly_quota':quota}
    with patch('history_sync.locate',return_value=path),patch('history_sync.read_public',return_value=read),patch('history_sync.publish') as publish:
     sync_once(api,catalog,'project',root,cache,failures,services)
    publish.assert_called_once()
    self.assertEqual(failures,{})
    self.assertEqual(services,{'pending':'pending_unavailable'})
    self.assertEqual(cache['task']['offset'],path.stat().st_size)
    self.assertNotIn('pending_quota',cache['task'])
    self.assertIn('/v2/usage',api.calls)
