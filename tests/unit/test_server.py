import base64
from pathlib import Path
import hashlib
import hmac
import time
import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from codex_workspace.domain import workspace
from codex_workspace.relay.app import app
from codex_workspace.relay.store import Store
from codex_workspace.relay import sessions


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        mode=Path(self.temp.name)/'e2ee-mode.json'
        mode.write_text(json.dumps({'v':1,'workspace':base64.urlsafe_b64encode(b'w'*32).decode().rstrip('=')}));mode.chmod(0o600)
        self.env=patch.dict('os.environ',{'WORKSPACE_CONFIG':'','WORKSPACE_DATA':self.temp.name,
            'OWNER_USERNAME':'owner',
            'CLIENT_KEY_HASH':hashlib.sha256(b'collector-test-key').hexdigest(),'PROJECT_ID':'project-example','PUBLIC_ORIGIN':'https://workspace.test'})
        self.env.start()
        self.client=TestClient(app,base_url='https://workspace.test',headers={'Origin':'https://workspace.test'});self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.env.stop();self.temp.cleanup()

    def test_pairing_requires_owner_csrf_and_collector_registration(self):
        from codex_workspace.crypto.workspace_crypto import encode
        body={'workspace':encode(b'w'*32),'id':encode(b'i'*32),'expires':int(time.time())+600}
        self.assertEqual(self.client.post('/v2/e2ee/pairing/register',json=body).status_code,401)
        self.assertEqual(self.client.post('/v2/e2ee/pairing/register',json=body,headers={'Authorization':'Bearer collector-test-key'}).status_code,200)
        query={k:body[k] for k in ('workspace','id')}
        self.assertEqual(self.client.post('/web/e2ee/pairing/read',json=query).status_code,401)
        _,csrf=self.browser_session()
        self.assertEqual(self.client.post('/web/e2ee/pairing/read',json=query).status_code,403)
        headers={'X-CSRF-Token':csrf}
        self.assertEqual(self.client.post('/web/e2ee/pairing/read',json=query,headers=headers).json(),{'payload':None})
        self.assertEqual(self.client.post('/web/e2ee/pairing/register',json=body,headers=headers).status_code,400)

    def test_encrypted_files_require_browser_session_csrf_and_collector_token(self):
        from codex_workspace.crypto.workspace_crypto import encode
        body={'workspace':'workspace','scope':'task','id':encode(b'f'*32),'size':3,'sha256':hashlib.sha256(b'abc').hexdigest()}
        self.assertEqual(self.client.post('/web/e2ee/files/start',json=body).status_code,401)
        self.assertEqual(self.client.post('/v2/e2ee/files/describe',json={}).status_code,401)
        _,csrf=self.browser_session()
        self.assertEqual(self.client.post('/web/e2ee/files/start',json=body).status_code,403)
        self.assertEqual(self.client.post('/web/e2ee/files/start',json=body,headers={'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(self.client.post('/v2/e2ee/files/start',json=body,headers={'Authorization':'Bearer collector-test-key'}).status_code,400)
        self.assertEqual(self.client.post('/web/e2ee/files/start',json={**body,'name':'private'},headers={'X-CSRF-Token':csrf}).status_code,400)

    def test_encrypted_channel_requires_separate_browser_and_collector_auth(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from codex_workspace.crypto.workspace_crypto import Context, encode, seal
        signing=ec.generate_private_key(ec.SECP256R1())
        context=Context('workspace','task','request',encode(b'n'*32),1)
        body={'envelope':seal(b'k'*32,signing,context,b'test-encrypted-request')}
        self.assertEqual(self.client.post('/web/e2ee/send',json=body).status_code,401)
        self.assertEqual(self.client.post('/v2/e2ee/read',json={}).status_code,401)
        _,csrf=self.browser_session()
        self.assertEqual(self.client.post('/web/e2ee/send',json=body).status_code,403)
        self.assertEqual(self.client.post('/web/e2ee/send',json=body,headers={'X-CSRF-Token':csrf}).status_code,200)
        query={'workspace':'workspace','scope':'task','kind':'request','after':0}
        self.assertEqual(self.client.post('/v2/e2ee/read',json=query,headers={'X-CSRF-Token':csrf}).status_code,401)
        result=self.client.post('/v2/e2ee/read',json=query,headers={'Authorization':'Bearer collector-test-key'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['records'][0]['envelope'],body['envelope'])
        self.assertEqual(self.client.post('/web/e2ee/send',json={'text':'plaintext'},headers={'X-CSRF-Token':csrf}).status_code,400)

    def test_health_and_auth_separation(self):
        self.assertEqual(self.client.get('/health').json()['mode'],'standalone-web')
        self.assertEqual(self.client.get('/web/login/config').status_code,409)
        self.assertEqual(self.client.post('/web/e2ee/read',json={}).status_code,401)
        self.assertEqual(self.client.post('/v2/e2ee/read',json={}).status_code,401)
        self.assertEqual(self.client.post('/web/state',json={}).status_code,409)
        self.browser_session()
        self.assertEqual(self.client.post('/v2/e2ee/read',json={}).status_code,401)


    def test_plaintext_diagnostics_are_unavailable_even_to_owner(self):
        _,csrf=self.browser_session()
        self.assertEqual(self.client.post('/web/diagnostics',json={},headers={'X-CSRF-Token':csrf}).status_code,409)


    def test_push_config_requires_session_and_csrf(self):
        self.assertEqual(self.client.post('/web/e2ee/push/config',json={}).status_code,401)
        token,csrf=self.browser_session()
        self.assertEqual(self.client.post('/web/e2ee/push/config',json={}).status_code,403)
        result=self.client.post('/web/e2ee/push/config',json={},headers={'X-CSRF-Token':csrf})
        self.assertEqual(result.status_code,200)
        self.assertEqual(set(result.json()),{'public_key'})

    def test_plaintext_collector_cannot_publish_catalog(self):
        headers={'Authorization':'Bearer collector-test-key'}
        body={'project_id':'project-example','threads':[]}
        self.assertEqual(self.client.post('/v2/catalog',json=body,headers=headers).status_code,409)
        self.assertEqual(self.client.post('/v2/inbox/claim',json={},headers=headers).status_code,409)


    def test_retired_telegram_login_cannot_issue_session(self):
        for path in ('/web/login/config','/web/login/session'):
            self.assertEqual(self.client.post(path,json={}).status_code,409)

    def browser_session(self):
        store=Store(self.temp.name)
        store.mutate(lambda s:s['bindings'].update(owner=42))
        from cryptography.hazmat.primitives.asymmetric import ec
        from codex_workspace.crypto.device_auth import sign,message
        from codex_workspace.crypto.workspace_crypto import encode,public_bytes,signer_id
        from codex_workspace.relay import device_auth
        root=ec.generate_private_key(ec.SECP256R1());device=ec.generate_private_key(ec.SECP256R1())
        pin=Path(self.temp.name)/'device-auth.json';pin.write_text(json.dumps({'workspace':encode(b'w'*32),'authority':encode(public_bytes(root))}));pin.chmod(0o600)
        payload={'v':1,'workspace':encode(b'w'*32),'origin':'https://workspace.test','owner':42,'devices':[{'id':signer_id(device),'public_key':encode(public_bytes(device)),'uid':42}],
                 'issued':int(time.time()),'expires':int(time.time())+86400,'revision':time.time_ns()//1000000}
        device_auth.registry(store,{'payload':payload,'signature':sign(root,message('registry',payload))},'https://workspace.test')
        self.auth_device=device
        token,csrf=sessions.issue(store,42,signer_id(device))
        self.client.cookies.set(sessions.COOKIE,token,domain='workspace.test',path='/')
        return token,csrf

    def test_device_proof_issues_cookie_once_and_requires_same_origin(self):
        from codex_workspace.crypto.device_auth import message,sign
        from codex_workspace.crypto.workspace_crypto import signer_id,encode,decode
        from cryptography.hazmat.primitives.asymmetric import utils
        self.browser_session();self.client.cookies.clear()
        device=signer_id(self.auth_device)
        self.assertEqual(self.client.post('/auth/device/challenge',json={'device':device},headers={'Origin':'https://evil.test'}).status_code,403)
        challenge=self.client.post('/auth/device/challenge',json={'device':device}).json()
        signature=decode(sign(self.auth_device,message('login','https://workspace.test',challenge['workspace'],device,challenge['nonce'],challenge['expires'])),maximum=80)
        r,s=utils.decode_dss_signature(signature)
        body={'device':device,'nonce':challenge['nonce'],'signature':encode(r.to_bytes(32,'big')+s.to_bytes(32,'big'))}
        result=self.client.post('/auth/device/session',json=body)
        self.assertEqual(result.status_code,200)
        for attribute in ('Secure','HttpOnly','SameSite=lax','Path=/'):self.assertIn(attribute,result.headers['set-cookie'])
        self.assertEqual(self.client.get('/auth/session').json()['workspace']['user']['id'],42)
        self.assertEqual(self.client.post('/auth/device/session',json=body).status_code,401)
        self.assertEqual(self.client.post('/v2/e2ee/auth/registry',json={}).status_code,401)

    def test_cookie_session_csrf_origin_and_logout_revocation(self):
        token,csrf=self.browser_session()
        self.assertEqual(self.client.get('/auth/session').json()['workspace']['user']['id'],42)
        self.assertEqual(self.client.post('/web/e2ee/push/config',json={}).status_code,403)
        self.assertEqual(self.client.post('/web/e2ee/push/config',json={},headers={'X-CSRF-Token':csrf,'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.post('/web/e2ee/push/config',json={},headers={'X-CSRF-Token':csrf}).status_code,200)
        self.assertEqual(self.client.post('/auth/logout',json={},headers={'X-CSRF-Token':csrf}).status_code,200)
        self.client.cookies.set(sessions.COOKIE,token,domain='workspace.test',path='/')
        self.assertEqual(self.client.get('/auth/session').status_code,401)

    def test_expired_browser_cookie_rejected(self):
        self.browser_session()
        db=Store(self.temp.name).connect()
        with db:db.execute('UPDATE browser_sessions SET expires=0')
        db.close()
        self.assertEqual(self.client.get('/auth/session').status_code,401)

    def test_reject_large_body(self):
        self.assertEqual(self.client.post('/web/state',content=b'x'*100001).status_code,413)

    def test_sqlite_rollback_preserves_state(self):
        store=Store(self.temp.name)
        store.mutate(lambda state:state.update(bindings={'owner':42}))
        def failed(state):
            state['bindings']['owner']=99
            raise ValueError('rollback')
        with self.assertRaises(ValueError):store.mutate(failed)
        self.assertEqual(store.mutate(lambda state:state['bindings']),{'owner':42})


if __name__ == '__main__':unittest.main()
