import fcntl
import json
from pathlib import Path
import tempfile
import unittest
import tomllib

from bridge import BridgeError
from cli_session import snapshot, writer_busy, command

T = '11111111-1111-1111-1111-111111111111'
U = '22222222-2222-2222-2222-222222222222'


class SessionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        folder = self.home / 'sessions/2026/09/21'
        folder.mkdir(parents=True)
        self.path = folder / f'rollout-test-{T}.jsonl'
        self.settings = dict(model='test-model', model_provider_id='openai',
            reasoning_effort='high', approval_policy='on-request', approvals_reviewer='auto_review',
            permission_profile={'type':'managed'}, cwd='/project', runtime_workspace_roots=['/project'])
        self.rows = [dict(type='session_meta', payload={'id':T}),
            dict(type='event_msg', payload=dict(type='thread_settings_applied', thread_id=T,
                                                thread_settings=self.settings)),
            dict(type='event_msg', payload=dict(type='task_started', turn_id=U))]

    def write(self):
        self.path.write_text(''.join(json.dumps(r)+'\n' for r in self.rows))

    def test_preserves_settings_and_excludes_unrelated_data(self):
        self.settings['secret_unknown_field'] = 'PRIVATE'
        self.write()
        result = snapshot(self.home, T)
        self.assertEqual(result['baseline'], U)
        self.assertEqual(result['settings']['reasoning_effort'], 'high')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_legacy_settings_bind_to_verified_session_identity(self):
        del self.rows[1]['payload']['thread_id']
        self.write()
        self.assertEqual(snapshot(self.home,T)['settings']['model'],'test-model')
        self.rows[1]['payload']['thread_id']=U
        self.write()
        with self.assertRaises(BridgeError):snapshot(self.home,T)

    def test_busy_lock_is_not_removed(self):
        folder = self.home / 'thread-writer-locks'
        folder.mkdir()
        path = folder / (T+'.lock')
        with path.open('w') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(writer_busy(self.home,T))
            self.assertEqual(snapshot(self.home,T)['status'],'busy')
        self.assertTrue(path.exists())
        self.assertFalse(writer_busy(self.home,T))

    def test_wrong_identity_and_partial_journal_fail(self):
        self.rows[0]['payload']['id']=U
        self.write()
        with self.assertRaises(BridgeError):snapshot(self.home,T)
        self.rows[0]['payload']['id']=T
        self.write()
        with self.path.open('a') as stream:stream.write('{')
        with self.assertRaises(BridgeError):snapshot(self.home,T)

    def test_incomplete_settings_fail(self):
        del self.settings['permission_profile']
        self.write()
        with self.assertRaises(BridgeError):snapshot(self.home,T)

    def test_command_preserves_model_and_restricted_permissions(self):
        self.settings['permission_profile'] = {'type':'managed', 'network':'restricted',
            'file_system':{'type':'restricted','entries':[
                {'path':{'type':'special','value':{'kind':'root'}},'access':'read'},
                {'path':{'type':'path','path':'/project/space " quote'},'access':'write'},
                {'path':{'type':'path','path':'/project/.git'},'access':'read','missing_path_behavior':'skip'}]}}
        self.write()
        args=command('/bin/codex',snapshot(self.home,T))
        config={}
        for index,value in enumerate(args):
            if value=='-c':config.update(tomllib.loads(args[index+1]))
        self.assertEqual(config['model'],'test-model')
        self.assertEqual(config['model_reasoning_effort'],'high')
        profile=config['permissions']['workspace_bridge']
        self.assertFalse(profile['network']['enabled'])
        self.assertEqual(profile['filesystem']['/project/.git'],'read')
        self.assertEqual(profile['filesystem']['/project/space " quote'],'write')
        self.assertEqual(args[-4:],['resume',T,'--json','-'])
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
        entries=self.settings['permission_profile']['file_system']['entries']
        entries.append(dict(entries[0]))
        self.write()
        self.assertEqual(command('/bin/codex',snapshot(self.home,T)),args)
        entries[-1]['access']='write'
        self.write()
        with self.assertRaises(BridgeError):command('/bin/codex',snapshot(self.home,T))


    def test_command_rejects_unrestricted_permissions(self):
        self.settings['permission_profile']={'type':'unrestricted'}
        self.write()
        with self.assertRaises(BridgeError):command('/bin/codex',snapshot(self.home,T))
