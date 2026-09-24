import time
import unittest
from codex_workspace.domain.quota import from_record, valid
from tests.unit.test_server import ServerTests


class QuotaTests(unittest.TestCase):
    def test_weekly_can_be_primary_or_secondary_and_no_secrets(self):
        window={'window_minutes':10080,'used_percent':63,'resets_at':1790344102}
        for key in ('primary','secondary'):
            result=from_record({'type':'event_msg','timestamp':'2026-09-20T22:20:14Z','payload':{'type':'token_count','rate_limits':{'limit_id':'codex',key:window,'credits':{'secret':'hidden'}}}})
            self.assertEqual(result['used_percent'],63)
            self.assertEqual(set(result),{'used_percent','resets_at','observed_at'})
        self.assertFalse(valid({'used_percent':float('nan'),'observed_at':1,'resets_at':2}))


class QuotaAPITests(ServerTests):
    def test_usage_auth_validation_and_monotonicity(self):
        now=int(time.time());data={'used_percent':63,'observed_at':now,'resets_at':now+1000}
        self.assertEqual(self.client.post('/v2/usage',json=data).status_code,401)
        headers={'Authorization':'Bearer collector-test-key'}
        self.assertEqual(self.client.post('/v2/usage',json={**data,'secret':'no'},headers=headers).status_code,400)
        self.assertEqual(self.client.post('/v2/usage',json=data,headers=headers).status_code,200)
        self.client.post('/v2/usage',json={**data,'observed_at':now-1,'used_percent':10},headers=headers)
        self.browser_session()
        self.assertEqual(self.client.get('/auth/session').json()['workspace']['weekly_quota'],data)

    def test_account_receives_quota(self):
        from codex_workspace.domain import domain, workspace
        state=domain.initial();state['bindings']={'owner':1,'friend':2};state['weekly_quota']={'used_percent':63,'observed_at':1,'resets_at':2}
        self.assertEqual(workspace.view(state,1,'owner',int(time.time()))['weekly_quota'],state['weekly_quota'])
