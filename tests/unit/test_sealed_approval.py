"""Signed approval must bind the exact local request and remain authorized."""
import json
import secrets
import time
from cryptography.hazmat.primitives.asymmetric import ec
from tests.unit.test_sealed_runtime import SealedRuntimeTests
from codex_workspace.devices.device_control import DeviceControl
from codex_workspace.devices.device_keys import DeviceKeys,delivery_scope
from codex_workspace.devices.sealed_access import LocalAccess
from codex_workspace.crypto.workspace_crypto import Context,CryptoError,decode,encode,public_bytes,seal

class ApprovalTests(SealedRuntimeTests):
    def setUp(self):
        super().setUp()
        self.trust=self.runtime.sealed.trust
        self.owner=self.trust.db.execute('SELECT * FROM devices').fetchone()
        self.access=LocalAccess(self.vault,self.trust)
        state=self.access.state(self.runtime.catalog)
        state['bindings']['member']=20
        state['thread_grants']['20']=['task']
        self.trust.db.execute('UPDATE encrypted_access SET value=?',(json.dumps(state),))
        self.member_key=ec.generate_private_key(ec.SECP256R1())
        self.member=self.trust.trust_device(public_bytes(self.member_key))
        DeviceKeys(self.vault,self.trust,self.runtime.channel).configure(self.member,{'task'})
        self.trust.db.execute('INSERT INTO encrypted_device_members VALUES(?,20)',(self.member,))
        self.control=DeviceControl(self.vault,self.trust,self.runtime.channel,self.runtime.catalog)

    def member_request(self):
        record=encode(secrets.token_bytes(32));intent={**self.intent,'request_id':record}
        envelope=seal(decode(self.key['key'],maximum=32),self.member_key,
                      Context(self.vault.workspace,'task','request',record,1),json.dumps(intent).encode())
        ident=self.runtime.sealed.receive('task',{'envelope':envelope})
        return json.loads(self.runtime.db.execute('SELECT payload FROM requests WHERE id=?',(ident,)).fetchone()[0])

    def approve(self,item,signer=None,**changes):
        now=int(time.time());scope=delivery_scope(public_bytes(self.device))
        args={'id':item['id'],'snapshot':item['snapshot'],'decision':'approved',**changes}
        command={'action':'decide','issued_at':now,'expires_at':now+600,'args':args}
        envelope=seal(decode(self.vault.active_key(scope)['key'],maximum=32),signer or self.device,
                      Context(self.vault.workspace,scope,'control',encode(secrets.token_bytes(32)),1),json.dumps(command).encode())
        return self.control.consume(self.owner,{'envelope':envelope})

    def test_only_exact_owner_approval_dispatches_member_request(self):
        item=self.member_request()
        self.assertEqual(self.runtime.pending()['messages'],[])
        with self.assertRaises(CryptoError):self.runtime.begin(item['id'],'task','old',api=self.runtime.api)
        with self.assertRaises(CryptoError):self.approve(item,snapshot='changed')
        with self.assertRaises(CryptoError):self.approve(item,signer=self.member_key)
        self.approve(item)
        self.assertEqual(self.runtime.begin(item['id'],'task','old',api=self.runtime.api)['text'],'private request')

    def test_approval_cannot_be_reused_for_another_request(self):
        first=self.member_request();second=self.member_request();self.approve(first)
        self.trust.db.execute("UPDATE requests SET status='pending' WHERE id=?",(second['id'],))
        with self.assertRaises(CryptoError):self.runtime.begin(second['id'],'task','old',api=self.runtime.api)

    def test_revoked_owner_invalidates_unexecuted_approval(self):
        item=self.member_request();self.approve(item);self.trust.revoke_device(self.owner['id'])
        with self.assertRaises(CryptoError):self.runtime.begin(item['id'],'task','old',api=self.runtime.api)

    def test_policy_relaxation_does_not_approve_existing_request(self):
        item=self.member_request()
        self.access.prepare(self.owner['id'],'member-policy',{'user_id':20,'requires_approval':False},self.runtime.catalog)
        self.access.reconcile()
        self.trust.db.execute("UPDATE requests SET status='pending' WHERE id=?",(item['id'],))
        with self.assertRaises(CryptoError):self.runtime.begin(item['id'],'task','old',api=self.runtime.api)
