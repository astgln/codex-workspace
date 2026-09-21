"""Regression tests for authentication trust, outbound data and anonymous budgets."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from cloud import login, workspace
from cloud.redaction import public_text, response_body
from server import sessions
from server.http_security import LoginBudget
from server.store import Store
from queue_transport import publish_results
from local_queue import Queue
from runtime_support import BridgeError
from workspace_client import API, MAX_RESPONSE_BYTES
from test_server import ServerTests


class SecurityAPITests(ServerTests):
    def test_collector_cannot_replace_telegram_keys(self):
        result = self.client.post('/v2/login-keys', json={'keys': [], 'fetched_at': 1},
                                  headers={'Authorization': 'Bearer collector-test-key'})
        self.assertEqual(result.status_code, 404)
        state = Store(self.temp.name).mutate(lambda s: s.copy())
        self.assertNotIn('login_jwks', state)
        self.assertNotIn('telegram_jwks_v2', state)

    def test_private_headers_cover_early_auth_failures_and_sessions(self):
        for result in (self.client.post('/web/state', json={}), self.client.get('/web/login/config')):
            self.assertEqual(result.headers['cache-control'], 'no-store')
            self.assertEqual(result.headers['x-content-type-options'], 'nosniff')
            self.assertEqual(result.headers['x-frame-options'], 'DENY')
            self.assertEqual(result.headers['referrer-policy'], 'no-referrer')
            self.assertIn('max-age=', result.headers['strict-transport-security'])
        self.browser_session()
        self.assertEqual(self.client.get('/auth/session').headers['cache-control'], 'no-store')

    def test_anonymous_login_has_bounded_verification_work(self):
        from server.app import app
        app.state.login_budget = LoginBudget(clock=lambda: 100)
        with patch('server.api.web_api', return_value={'statusCode':401,'body':'{}'}) as verification:
            for _ in range(30):
                self.assertEqual(self.client.post('/web/login/session',json={}).status_code,401)
            limited=self.client.post('/web/login/session',json={})
            self.assertEqual(limited.status_code,429)
            self.assertEqual(verification.call_count,30)
            self.assertIn('retry-after',limited.headers)
        self.assertEqual(self.client.get('/health').status_code,200)


class TrustUpgradeTests(unittest.TestCase):
    def test_old_collector_cache_is_ignored_and_old_cookies_revoked_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            store.mutate(lambda state:state.update(login_jwks={'keys':['untrusted'],'fetched_at':1000}))
            self.assertIsNone(login.cached_keys(store.mutate(lambda s:s.copy()),1001))
            old,_=sessions.issue(store,42)
            with store.connect() as db:
                db.execute('CREATE TABLE push_subscriptions(id TEXT)')
                db.execute("INSERT INTO push_subscriptions VALUES('obsolete-device')")
            sessions.upgrade_auth_trust(store)
            with self.assertRaises(workspace.Unauthorized):sessions.verify(store,old)
            self.assertNotIn('login_jwks',store.mutate(lambda s:s.copy()))
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM push_subscriptions').fetchone()[0],0)
            current,_=sessions.issue(store,42)
            sessions.upgrade_auth_trust(store)
            self.assertEqual(sessions.verify(store,current)[0],42)

    def test_budget_refills_without_trusting_forwarded_ip_headers(self):
        now=[100.0];budget=LoginBudget(clock=lambda:now[0])
        for _ in range(30):self.assertEqual(budget.take('web/login/session'),0)
        self.assertEqual(budget.take('web/login/session'),2)
        now[0]+=2
        self.assertEqual(budget.take('web/login/session'),0)
        self.assertEqual(budget.take('web/state'),0)


class OutboundTests(unittest.TestCase):
    def test_secrets_filtered_in_history_answers_errors_plans_and_diffs(self):
        samples=['sk-'+'a'*32, 'ghp_'+'b'*32, '123456789:'+'c'*35,
                 'Authorization: Bearer synthetic-bearer', 'PASSWORD=synthetic-password',
                 '{"access_token":"synthetic-json","other":"kept"}',
                 '-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-private\n-----END OPENSSH PRIVATE KEY-----',
                 '-----BEGIN RSA PRIVATE KEY-----\nsynthetic-partial',
                 'https://user:synthetic-url@example.test/']
        for text in samples:
            filtered=public_text(text)
            self.assertNotEqual(filtered,text)
            self.assertNotIn('synthetic-',filtered)
            self.assertEqual(public_text(filtered),filtered)
        body={'id':-1,'thread':'task','revision':7,'status':'completed','events':[
            {'type':'agent_message','text':samples[0]}, {'type':'error','message':samples[3]},
            {'type':'file_change','path':'config.txt','patch':'+'+samples[4]},
            {'type':'plan_update','plan':[{'step':samples[1],'status':'completed'}]}]}
        filtered=response_body(body)
        self.assertEqual(filtered['revision'],7)
        self.assertNotIn('synthetic-',json.dumps(filtered))
        with tempfile.TemporaryDirectory() as directory, Queue(Path(directory)) as queue:
            with queue.db:queue.db.execute("INSERT INTO requests(id,payload,status,result) VALUES(-1,'{}','publishing',?)",(json.dumps(body),))
            api=Mock();publish_results(queue,api)
            self.assertEqual(api.call.call_args.args,('/v2/responses',filtered))
            self.assertEqual((Path(directory)/'web-queue.sqlite3').stat().st_mode & 0o777,0o600)

    def test_api_rejects_host_injection_and_oversized_or_nonobject_replies(self):
        api=object.__new__(API);api.url='https://example.apigw.yandexcloud.net';api.key='synthetic-key'
        for path in ('@evil.test/x','//evil.test/x','/v2/x?token=leak','/v2/\\evil'):
            with patch('workspace_client.urllib.request.build_opener') as opener:
                with self.assertRaises(BridgeError):api.call(path,{})
                opener.assert_not_called()
        for raw in (b'x'*(MAX_RESPONSE_BYTES+1),b'[]'):
            response=io.BytesIO(raw);opener=Mock();opener.open.return_value=response
            with patch('workspace_client.urllib.request.build_opener',return_value=opener):
                with self.assertRaises(BridgeError):api.call('/v2/inbox/claim',{})
