import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from cryptography.hazmat.primitives.asymmetric import ec
from codex_workspace.devices.device_keys import DeviceKeys
from codex_workspace.devices.device_trust import TrustStore
from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.devices.sealed_access import LocalAccess
from codex_workspace.agent.sealed_channel import SealedChannel
from codex_workspace.crypto.workspace_crypto import CryptoError,public_bytes

class AccessTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        self.vault=KeyVault.create(root/'keys','https://workspace.example');self.addCleanup(self.vault.db.close)
        self.trust=TrustStore(root/'trust',self.vault.workspace);self.addCleanup(self.trust.db.close)
        self.keys=DeviceKeys(self.vault,self.trust,SealedChannel(Mock(url=self.vault.origin),self.vault))
        self.catalog={'projects':[{'id':'p','title':'Project'}],'threads':[{'id':'a','project_id':'p'},{'id':'b','project_id':'p','read_only':True}]}
        for scope in ['workspace','a','b']:self.vault.scope_key(scope)
        self.owner=self.trust.trust_device(public_bytes(ec.generate_private_key(ec.SECP256R1())))
        self.member=self.trust.trust_device(public_bytes(ec.generate_private_key(ec.SECP256R1())))
        self.keys.configure(self.owner,{'workspace','a','b'});self.keys.configure(self.member,set())
        self.access=LocalAccess(self.vault,self.trust);self.access.bootstrap(10,[{'id':20,'username':'member'}])
        self.trust.db.execute('INSERT INTO encrypted_device_members VALUES(?,20)',(self.member,))

    def grants(self,**overrides):
        body={'user_id':20,'threads':[],'projects':['p'],'denied_threads':['b'],**overrides}
        self.access.prepare(self.owner,'grants',body,self.catalog);self.access.reconcile()

    def test_local_project_grants_denies_and_new_tasks(self):
        self.grants()
        self.assertEqual(self.access.authorize(self.member,'a',self.catalog),{'sender':20,'requires_approval':True})
        with self.assertRaises(CryptoError):self.access.authorize(self.member,'b',self.catalog)
        self.catalog['threads'].append({'id':'new','project_id':'p'})
        self.access.sync_catalog(self.catalog)
        scopes=json.loads(self.trust.db.execute('SELECT scopes FROM device_grants WHERE device=?',(self.member,)).fetchone()[0])
        self.assertEqual(set(scopes),{'a','new'})
        self.access.prepare(self.owner,'member-policy',{'user_id':20,'requires_approval':False},self.catalog);self.access.reconcile()
        self.assertFalse(self.access.authorize(self.member,'new',self.catalog)['requires_approval'])

    def test_member_cannot_grant_own_access(self):
        with self.assertRaises(CryptoError):self.access.prepare(self.member,'grants',{'user_id':20,'threads':['a']},self.catalog)

    def test_revocation_rotates_once_even_after_crash(self):
        self.grants();before=self.vault.active_key('a')['epoch']
        self.access.prepare(self.owner,'grants',{'user_id':20,'threads':[],'projects':[],'denied_threads':[]},self.catalog)
        with self.assertRaises(CryptoError):self.vault.active_key('a')
        original=self.vault.scope_key
        def interrupted(scope,**kwargs):
            value=original(scope,**kwargs)
            if kwargs.get('rotate'):raise OSError('simulated crash')
            return value
        with patch.object(self.vault,'scope_key',side_effect=interrupted):
            with self.assertRaises(OSError):self.access.reconcile()
        with self.assertRaises(CryptoError):self.vault.active_key('a')
        self.access.reconcile()
        self.assertEqual(self.vault.active_key('a')['epoch'],before+1)
        with self.assertRaises(CryptoError):self.access.authorize(self.member,'a',self.catalog)
        self.assertFalse(self.access.reconcile())

    def test_member_catalog_excludes_denied_tasks_and_owner_roster(self):
        from codex_workspace.devices.device_keys import delivery_scope
        self.grants()
        channel=Mock()
        self.access.publish(self.catalog,channel)
        public=self.trust.db.execute('SELECT public_key FROM devices WHERE id=?',(self.member,)).fetchone()[0]
        own=[call.args for call in channel.snapshot.call_args_list if call.args[0]==delivery_scope(public)]
        records={args[2]:args[3] for args in own}
        self.assertEqual(records['index']['threads'],['a'])
        self.assertNotIn('task:b',records)
        self.assertEqual(records['access']['user']['id'],20)
        self.assertEqual(records['access']['user']['role'],'member')
        self.assertEqual(records['access']['members'],[])
