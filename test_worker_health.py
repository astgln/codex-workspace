import unittest
from unittest.mock import Mock
from cloud.worker_status import save
from worker_health import summary, publish
from test_server import ServerTests


class WorkerHealthTests(unittest.TestCase):
    def test_summary_drops_identifiers_and_content(self):
        result=summary({'status':'waiting_for_tasks','requests':[
            {'id':-1,'reason':'desktop_writer_lock','text':'private'},
            {'id':-2,'reason':'task_settings_unavailable'}]})
        self.assertNotIn('private',str(result))
        self.assertNotIn('id',result)
        state={};save(state,result,10)
        self.assertEqual(state['worker_status']['waiting']['desktop_writer_lock'],1)
        self.assertEqual(summary({'status':'needs_reconciliation','id':-1})['unresolved'],1)
        self.assertEqual(summary({'status':'needs_reconciliation','ids':[-1,-2]})['unresolved'],2)

    def test_failure_is_best_effort_and_validation_rejects_private_fields(self):
        result=summary({'status':'idle'})
        api=Mock();api.call.side_effect=OSError('offline')
        self.assertFalse(publish(api,{'status':'idle'}))
        for bad in ({**result,'path':'private'}, {**result,'unresolved':True},
                    {**result,'unresolved':-1}, {**result,'status':'arbitrary text'},
                    {**result,'waiting':{'secret':1}}):
            with self.assertRaises(ValueError):save({},bad,10)


class WorkerHealthAPITests(ServerTests):
    def test_collector_only_write_and_owner_only_read(self):
        result=summary({'status':'waiting_for_tasks','requests':[{'reason':'desktop_writer_lock'}]})
        self.assertEqual(self.client.post('/v2/worker/status',json=result).status_code,401)
        headers={'Authorization':'Bearer collector-test-key'}
        self.assertEqual(self.client.post('/v2/worker/status',json={**result,'text':'secret'},headers=headers).status_code,400)
        self.assertEqual(self.client.post('/v2/worker/status',json=result,headers=headers).status_code,200)
        _,csrf=self.browser_session()
        response=self.client.post('/web/diagnostics',json={},headers={'X-CSRF-Token':csrf})
        self.assertEqual(response.json()['worker']['waiting']['desktop_writer_lock'],1)
        self.assertNotIn('worker_status',self.client.get('/auth/session').json()['workspace'])
