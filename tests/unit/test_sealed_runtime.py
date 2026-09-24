import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from cryptography.hazmat.primitives.asymmetric import ec
from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.agent.sealed_runtime import SealedRuntime
from codex_workspace.agent.local_queue import Queue
from codex_workspace.agent.runtime_support import BridgeError
from codex_workspace.crypto.workspace_crypto import Context, encode, decode, seal, public_bytes, open_envelope

class SealedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.vault=KeyVault.create(self.root/'keys.db','https://workspace.example');self.addCleanup(self.vault.db.close)
        self.key=self.vault.scope_key('task')
        self.api=Mock(url=self.vault.origin)
        self.runtime=SealedRuntime(self.root,self.vault,self.api,{'threads':[{'id':'task'}]});self.addCleanup(self.runtime.close)
        self.device=ec.generate_private_key(ec.SECP256R1())
        self.runtime.sealed.trust.trust_device(public_bytes(self.device))
        now=int(time.time());record=encode(secrets.token_bytes(32))
        self.intent={'v':1,'workspace':self.vault.workspace,'thread':'task','request_id':record,'issued_at':now,'expires_at':now+600,'text':'private request','attachments':[]}
        self.envelope=seal(decode(self.key['key'],maximum=32),self.device,Context(self.vault.workspace,'task','request',record,1),json.dumps(self.intent).encode())
        self.api.call.return_value={'records':[{'sequence':1,'envelope':self.envelope}],'after':1,'more':False}

    def test_crash_between_intake_and_cursor_does_not_duplicate_execution(self):
        self.runtime.sealed.receive('task',{'envelope':self.envelope})
        self.runtime.tick()
        messages=self.runtime.pending()['messages'];self.assertEqual(len(messages),1)
        ident=messages[0]['id']
        self.assertEqual(self.runtime.begin(ident,'task','old',api=self.runtime.api)['text'],'private request')
        self.runtime.sent(ident,json.loads(self.runtime.db.execute('SELECT dispatch FROM requests').fetchone()[0])['marker'])
        dispatch=json.loads(self.runtime.db.execute('SELECT dispatch FROM requests').fetchone()[0])
        self.runtime.publish(ident,{'thread':'task','marker':dispatch['marker'],'turn_id':'new','status':'completed','events':[{'type':'agent_message','id':'a','text':'private answer'}]})
        from codex_workspace.agent.queue_transport import publish_results
        publish_results(self.runtime,self.runtime.api)
        path,body=next(call.args for call in self.api.call.call_args_list if call.args[0]=='/v2/e2ee/publish' and call.args[1]['envelope']['context'][2]=='response' and call.args[1]['envelope']['context'][4]>1)
        self.assertEqual(path,'/v2/e2ee/publish')
        self.assertNotIn('private answer',json.dumps(body))
        self.assertEqual(body['envelope']['context'][3],self.intent['request_id'])
        response=json.loads(open_envelope(decode(self.key['key'],maximum=32),self.vault.authority.public_key(),
            Context(*body['envelope']['context']),body['envelope']))
        self.assertEqual(response['request']['text'],'private request')
        self.assertEqual(response['result']['events'][0]['text'],'private answer')
        self.assertEqual(response['attachment_signer'],encode(public_bytes(self.device)))
        self.assertEqual(self.runtime.db.execute('SELECT status FROM requests').fetchone()[0],'complete')

    def test_plaintext_endpoints_never_pass_through(self):
        for path in ['/v2/inbox/claim','/v2/catalog','/v2/worker/status']:
            with self.assertRaises(BridgeError):self.runtime.api.call(path,{'private':'text'})
        self.api.call.assert_not_called()

    def test_pin_blocks_legacy_queue_even_if_keys_are_missing(self):
        pin=self.root/'e2ee-required';pin.write_text('codex-workspace/e2ee/v1\n');pin.chmod(0o600)
        with Queue(self.root) as queue:
            with self.assertRaises(BridgeError):queue.tick(self.api)
            with self.assertRaises(BridgeError):queue.begin(-1,'task','old',api=self.api)
        self.api.call.assert_not_called()

    def test_waiting_reason_is_published_under_task_key(self):
        self.runtime.sealed.receive('task',{'envelope':self.envelope})
        ident=self.runtime.pending()['messages'][0]['id']
        self.runtime.channel.snapshot=Mock()
        self.runtime.health({'status':'waiting_for_tasks','requests':[{'id':ident,'reason':'desktop_writer_lock'}]})
        args=self.runtime.channel.snapshot.call_args_list[0].args
        self.assertEqual(args[:3],('task','response','dispatch:'+self.intent['request_id']))
        self.assertEqual(args[3]['reason'],'desktop_writer_lock')
        self.runtime.health({'status':'idle'})
        self.assertIsNone(self.runtime.channel.snapshot.call_args_list[-2].args[3]['reason'])
