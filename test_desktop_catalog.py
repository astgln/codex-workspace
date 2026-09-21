from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch
from desktop_catalog import discover, refresh
from runtime_support import BridgeError
from rollout_history import read_public

T = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


class DesktopCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = {'local-projects': {'p': {'id':'p','name':'Project'}, 'q':{'id':'q','name':'Other'}},
                      'thread-project-assignments': {T:{'projectKind':'local','projectId':'p'}},
                      'projectless-thread-ids': []}
        self.write_state()
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db, db:
            db.execute('create table threads(id,name,source,archived)')
            db.execute('insert into threads values(?,?,?,0)', (T,'Task','vscode'))
            db.execute('insert into threads values(?,?,?,0)', ('unassigned','Private','vscode'))
        self.previous = {'project_id':'scope','projects':[], 'threads':[{'id':T,'read_only':True}]}

    def write_state(self):
        (self.home/'.codex-global-state.json').write_text(json.dumps(self.state))

    def test_exact_identity_and_no_cwd_inference(self):
        result = discover(self.home,self.previous,{})
        self.assertEqual(len(result['threads']),1)
        self.assertEqual(result['threads'][0]['project_id'],'p')
        self.assertTrue(result['threads'][0]['read_only'])
        self.assertEqual(result['threads'][0]['status'],'unknown')
        self.state['thread-project-assignments'][T]['projectId']='q'
        self.state['local-projects']['q']['name']='Renamed'
        self.write_state()
        result = discover(self.home,self.previous,{})
        self.assertEqual(result['threads'][0]['project_id'],'q')
        self.assertEqual(result['projects'][1]['title'],'Renamed')

    def test_activity_timestamp_uses_millisecond_precision(self):
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db, db:
            db.execute('alter table threads add column updated_at')
            db.execute('alter table threads add column updated_at_ms')
            db.execute('update threads set updated_at=100,updated_at_ms=123456 where id=?',(T,))
        result=discover(self.home,self.previous,{})
        self.assertEqual(result['threads'][0]['updated_at'],123.456)

    def test_archived_and_projectless_disappear(self):
        self.state['projectless-thread-ids']=[T]; self.write_state()
        self.assertEqual(discover(self.home,self.previous,{})['threads'],[])
        self.state['projectless-thread-ids']=[]; self.write_state()
        with closing(sqlite3.connect(self.home/'state_5.sqlite')) as db, db:
            db.execute('update threads set archived=1 where id=?',(T,))
        self.assertEqual(discover(self.home,self.previous,{})['threads'],[])

    def test_activity_requires_live_writer(self):
        cache={T:{'activity':{'state':'active','turn_id':'turn'}}}
        with patch('desktop_catalog.writer_busy',return_value=False):
            self.assertEqual(discover(self.home,self.previous,cache)['threads'][0]['status'],'unknown')
        with patch('desktop_catalog.writer_busy',return_value=True):
            self.assertEqual(discover(self.home,self.previous,cache)['threads'][0]['status'],'active')
        cache[T]['activity']['state']='idle'
        self.assertEqual(discover(self.home,self.previous,cache)['threads'][0]['status'],'idle')

    def test_unknown_schema_and_failed_publish_preserve_catalog(self):
        path=self.home/'catalog.json';path.write_text(json.dumps(self.previous));before=path.read_bytes()
        api=Mock();api.call.side_effect=BridgeError('offline')
        with self.assertRaises(BridgeError):refresh(api,path,self.home,{})
        self.assertEqual(path.read_bytes(),before)
        del self.state['thread-project-assignments'];self.write_state()
        with self.assertRaises(BridgeError):refresh(api,path,self.home,{})
        self.assertEqual(path.read_bytes(),before)

    def test_incremental_terminal_does_not_close_other_turn(self):
        path=self.home/'rollout.jsonl'
        records=[{'type':'session_meta','payload':{'id':T}},
                 {'type':'event_msg','payload':{'type':'task_started','turn_id':'new'}}]
        path.write_text(''.join(json.dumps(r)+'\n' for r in records))
        first=read_public(path,T)
        with path.open('a') as f:f.write(json.dumps({'type':'event_msg','payload':{'type':'task_complete','turn_id':'old'}})+'\n')
        second=read_public(path,T,first['source_offset'],first['activity'])
        self.assertEqual(second['activity'],first['activity'])
        with path.open('a') as f:f.write(json.dumps({'type':'event_msg','payload':{'type':'turn_aborted','turn_id':'new'}})+'\n')
        self.assertEqual(read_public(path,T,second['source_offset'],second['activity'])['activity']['state'],'idle')
