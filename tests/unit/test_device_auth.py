import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import ec,utils
from codex_workspace.crypto.device_auth import message,sign
from codex_workspace.crypto.workspace_crypto import encode,decode,public_bytes,signer_id
from codex_workspace.relay import device_auth,sessions
from codex_workspace.relay.store import Store
from codex_workspace.domain.workspace import Unauthorized

class DeviceAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name);self.origin='https://workspace.test'
        self.root=ec.generate_private_key(ec.SECP256R1());self.device=ec.generate_private_key(ec.SECP256R1())
        self.workspace=encode(b'w'*32);self.ident=signer_id(self.device)
        p=Path(self.temp.name)/'device-auth.json';p.write_text(json.dumps({'workspace':self.workspace,'authority':encode(public_bytes(self.root))}));p.chmod(0o600)
        self.publish()

    def publish(self,revision=1,devices=None):
        now=int(time.time())
        payload={'v':1,'workspace':self.workspace,'origin':self.origin,'owner':42,'devices':devices if devices is not None else [{'id':self.ident,'uid':42,'public_key':encode(public_bytes(self.device))}],'issued':now,'expires':now+86400,'revision':revision}
        body={'payload':payload,'signature':sign(self.root,message('registry',payload))}
        device_auth.registry(self.store,body,self.origin)
        return body

    def proof(self,challenge=None,private=None,origin=None):
        challenge=challenge or device_auth.challenge(self.store,{'device':self.ident},self.origin)
        raw=decode(sign(private or self.device,message('login',origin or self.origin,self.workspace,self.ident,challenge['nonce'],challenge['expires'])),maximum=80)
        r,s=utils.decode_dss_signature(raw)
        return {'device':self.ident,'nonce':challenge['nonce'],'signature':encode(r.to_bytes(32,'big')+s.to_bytes(32,'big'))}

    def test_valid_login_replay_and_session_revocation(self):
        proof=self.proof();uid,device=device_auth.authenticate(self.store,proof,self.origin)
        self.assertEqual((uid,device),(42,self.ident))
        with self.assertRaises(Unauthorized):device_auth.authenticate(self.store,proof,self.origin)
        token,csrf=sessions.issue(self.store,uid,device)
        self.assertEqual(sessions.verify(self.store,token),(uid,csrf))
        self.publish(2,[])
        with self.assertRaises(Unauthorized):sessions.verify(self.store,token)
        with self.assertRaises(Unauthorized):device_auth.authenticate(self.store,self.proof(),self.origin)

    def test_forgery_wrong_origin_and_expired_challenge(self):
        for proof in [self.proof(private=self.root),self.proof(origin='https://evil.test')]:
            with self.assertRaises(Unauthorized):device_auth.authenticate(self.store,proof,self.origin)
        proof=self.proof()
        db=self.store.connect()
        with db:db.execute('UPDATE device_challenges SET expires=0')
        db.close()
        with self.assertRaises(Unauthorized):device_auth.authenticate(self.store,proof,self.origin)

    def test_registry_tamper_rollback_and_expiry(self):
        old=self.publish(2)
        tampered=json.loads(json.dumps(old));tampered['payload']['owner']=123
        with self.assertRaises(Exception):device_auth.registry(self.store,tampered,self.origin)
        self.publish(3,[])
        with self.assertRaises(ValueError):device_auth.registry(self.store,old,self.origin)
        with patch('codex_workspace.relay.device_auth.time.time',return_value=time.time()+86401):
            with self.assertRaises(Unauthorized):device_auth.current(self.store)

    def test_old_cookie_and_unregistered_key_cannot_login(self):
        token,_=sessions.issue(self.store,42)
        with self.assertRaises(Unauthorized):sessions.verify(self.store,token)
        proof=self.proof();proof['device']=signer_id(self.root)
        with self.assertRaises(Unauthorized):device_auth.authenticate(self.store,proof,self.origin)

    def test_public_pin_install_is_idempotent_and_refuses_replacement(self):
        from codex_workspace.relay.bootstrap import install_pin
        directory=Path(self.temp.name)/'new-relay'
        value={'workspace':self.workspace,'authority':encode(public_bytes(self.root))}
        install_pin(directory,value);install_pin(directory,value)
        self.assertEqual((directory/'device-auth.json').stat().st_mode & 0o777,0o600)
        with self.assertRaises(ValueError):install_pin(directory,{**value,'authority':encode(public_bytes(self.device))})
