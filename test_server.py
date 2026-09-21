import hashlib
import hmac
import time
import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from cloud import workspace
from server.app import app
from server.store import Store
from server import sessions


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict('os.environ',{'WORKSPACE_CONFIG':'','WORKSPACE_DATA':self.temp.name,
            'TELEGRAM_BOT_TOKEN':'123:test-only','OWNER_USERNAME':'owner',
            'CLIENT_KEY_HASH':hashlib.sha256(b'collector-test-key').hexdigest(),'PROJECT_ID':'project-example','PUBLIC_ORIGIN':'https://workspace.test'})
        self.env.start()
        self.keys=patch('cloud.login.public_keys',side_effect=RuntimeError('offline test'));self.keys.start()
        self.client=TestClient(app,base_url='https://workspace.test',headers={'Origin':'https://workspace.test'});self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.keys.stop();self.env.stop();self.temp.cleanup()

    def test_health_and_auth_separation(self):
        self.assertEqual(self.client.get('/health').json()['mode'],'standalone-web')
        self.assertEqual(self.client.post('/web/state',json={}).status_code,401)
        self.assertEqual(self.client.post('/v2/inbox/claim',json={}).status_code,401)
        self.assertEqual(self.client.post('/web/state',json={},headers={'Authorization':'Bearer collector-test-key'}).status_code,401)
        self.assertEqual(self.client.get('/web/login/config').status_code,200)
        self.assertEqual(self.client.post('/v2/inbox/validate',json={}).status_code,401)
        self.browser_session()
        self.assertEqual(self.client.post('/v2/inbox/validate',json={}).status_code,401)
        result=self.client.post('/v2/inbox/validate',json={'id':-999},headers={'Authorization':'Bearer collector-test-key'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json(),{'allowed':False})

    def test_diagnostics_requires_owner_cookie_and_csrf(self):
        self.assertEqual(self.client.post('/web/diagnostics',json={}).status_code,401)
        _,csrf=self.browser_session()
        self.assertEqual(self.client.post('/web/diagnostics',json={}).status_code,403)
        result=self.client.post('/web/diagnostics',json={},headers={'X-CSRF-Token':csrf})
        self.assertEqual(result.status_code,200)
        self.assertIn('notifications',result.json())
        Store(self.temp.name).mutate(lambda s:s['bindings'].update(owner=99,friend=42))
        self.assertEqual(self.client.post('/web/diagnostics',json={},headers={'X-CSRF-Token':csrf}).status_code,403)

    def test_push_config_requires_session_and_csrf(self):
        self.assertEqual(self.client.post('/web/push/config',json={}).status_code,401)
        token,csrf=self.browser_session()
        self.assertEqual(self.client.post('/web/push/config',json={}).status_code,403)
        result=self.client.post('/web/push/config',json={},headers={'X-CSRF-Token':csrf})
        self.assertEqual(result.status_code,200)
        self.assertEqual(set(result.json()),{'public_key'})

    def test_catalog_is_project_scoped(self):
        headers={'Authorization':'Bearer collector-test-key'}
        body={'project_id':'project-example','threads':[{'id':'thread-launcher','title':'Launcher','project_id':'project-example'}]}
        self.assertEqual(self.client.post('/v2/catalog',json=body,headers=headers).status_code,200)
        self.assertEqual(self.client.post('/v2/catalog',json={**body,'project_id':'other'},headers=headers).status_code,403)
        result=self.client.post('/v2/inbox/claim',json={},headers=headers)
        self.assertEqual(result.json(),{'message':None})

    def test_widget_login_verified_bound_and_replay_rejected(self):
        data={'id':42,'first_name':'Owner','username':'owner','auth_date':int(time.time())}
        canonical='\n'.join(f'{k}={v}' for k,v in sorted(data.items()))
        data['hash']=hmac.new(hashlib.sha256(b'123:test-only').digest(),canonical.encode(),hashlib.sha256).hexdigest()
        challenge=self.client.get('/web/login/config').json()['challenge']
        body={'widget_data':data,'challenge':challenge}
        result=self.client.post('/web/login/session',json=body)
        self.assertEqual(result.status_code,200)
        cookie=result.headers['set-cookie']
        for attribute in ('Secure','HttpOnly','SameSite=lax','Path=/'):
            self.assertIn(attribute,cookie)
        self.assertNotIn('Domain=',cookie)
        self.assertNotIn('token',result.json())
        csrf=self.client.get('/auth/session').json()['csrf']
        view=self.client.post('/web/state',json={},headers={'X-CSRF-Token':csrf})
        self.assertEqual(view.json()['user'],{'id':42})
        fresh=self.client.get('/web/login/config').json()['challenge']
        self.assertEqual(self.client.post('/web/login/session',json={**body,'challenge':fresh}).status_code,401)
        self.assertEqual(self.client.post('/web/login/session',json={**body,'id_token':'ambiguous'}).status_code,401)

    def test_forged_widget_never_binds_owner(self):
        body={'widget_data':{'id':99,'username':'owner','auth_date':int(time.time()),'hash':'0'*64},
              'challenge':self.client.get('/web/login/config').json()['challenge']}
        self.assertEqual(self.client.post('/web/login/session',json=body).status_code,401)
        self.assertEqual(Store(self.temp.name).mutate(lambda s:s['bindings']),{})

    def browser_session(self):
        store=Store(self.temp.name)
        store.mutate(lambda s:s['bindings'].update(owner=42))
        token,csrf=sessions.issue(store,42)
        self.client.cookies.set(sessions.COOKIE,token,domain='workspace.test',path='/')
        return token,csrf

    def test_cookie_session_csrf_origin_and_logout_revocation(self):
        token,csrf=self.browser_session()
        self.assertEqual(self.client.get('/auth/session').json()['workspace']['user']['id'],42)
        self.assertEqual(self.client.post('/web/state',json={}).status_code,403)
        self.assertEqual(self.client.post('/web/state',json={},headers={'X-CSRF-Token':csrf,'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.post('/web/state',json={},headers={'X-CSRF-Token':csrf}).status_code,200)
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
