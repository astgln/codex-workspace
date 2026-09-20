import json
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import time
from cloud import domain, workspace
from bridge import BridgeError
from web_client import Queue


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.api=Mock();self.api.call.return_value={"allowed":True}
        self.temp = tempfile.TemporaryDirectory()
        self.q = Queue(Path(self.temp.name))
        self.item = {'id':-1,'thread':'thread-one','text':'external text','snapshot':'a'*64,'lease':'lease','created':1000}
        self.q.receive(self.item)

    def tearDown(self):
        self.q.db.close(); self.temp.cleanup()

    def receipt(self):
        class FakeAPI:
            def call(self,path,body): return {'status':'delivered'}
        self.q.receipts(FakeAPI())

    def test_receipt_before_pending(self):
        self.assertEqual(self.q.pending()['messages'],[])
        self.receipt()
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'pending')

    def test_dispatch_intent_survives_restart_and_cannot_repeat(self):
        self.receipt()
        dispatch=self.q.begin(-1,'thread-one','baseline-turn',api=self.api)
        self.q.db.close();self.q=Queue(Path(self.temp.name))
        with self.assertRaises(BridgeError): self.q.begin(-1,'thread-one','baseline-turn',api=self.api)
        self.assertEqual(self.q.pending()['messages'][0]['local_status'],'dispatching')
        with self.assertRaises(BridgeError): self.q.sent(-1,'wrong-marker')
        self.q.sent(-1,dispatch['marker'])

    def test_result_requires_matching_marker_thread_and_turn(self):
        self.receipt(); dispatch=self.q.begin(-1,'thread-one','baseline-turn',api=self.api);self.q.sent(-1,dispatch['marker'])
        body={'marker':dispatch['marker'],'thread':'thread-one','turn_id':'new-turn','status':'completed','events':[{'type':'agent_message','text':'reply'}]}
        for change in ({'marker':'other'},{'thread':'other'},{'turn_id':''},{'turn_id':'baseline-turn'}):
            with self.assertRaises(BridgeError): self.q.publish(-1,{**body,**change})
        self.q.publish(-1,body)
        row=self.q.db.execute('SELECT * FROM requests WHERE id=-1').fetchone()
        self.assertEqual(row['status'],'publishing')
        self.assertEqual(json.loads(row['result'])['revision'],1)

    def test_redelivery_cannot_replace_approved_payload(self):
        with self.assertRaises(BridgeError): self.q.receive({**self.item,'snapshot':'b'*64})
        with self.assertRaises(BridgeError): self.q.receive({**self.item,'thread':'other'})
        with self.assertRaises(BridgeError): self.q.receive({**self.item,'text':'changed but same digest'})

    def test_response_turn_is_pinned_across_revisions(self):
        self.receipt();dispatch=self.q.begin(-1,'thread-one','baseline-turn',api=self.api);self.q.sent(-1,dispatch['marker'])
        body={'marker':dispatch['marker'],'thread':'thread-one','turn_id':'new-turn','status':'running','events':[]}
        self.q.publish(-1,body)
        with self.q.db:self.q.db.execute("UPDATE requests SET status='dispatched' WHERE id=-1")
        with self.assertRaises(BridgeError):self.q.publish(-1,{**body,'turn_id':'unrelated-turn'})
        self.q.publish(-1,{**body,'status':'completed'})

    def test_files_must_be_verified_before_dispatch_and_unchanged_afterward(self):
        data=b'approved file bytes'
        attachment={'id':'a'*32,'name':'Connection.log','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        item={**self.item,'id':-2,'attachments':[attachment]}
        self.q.receive(item);self.receipt()
        with self.assertRaises(BridgeError):self.q.begin(-2,'thread-one','baseline-turn',api=self.api)
        class FakeAPI:
            def call(self,path,body):return {'data':base64.b64encode(data).decode(),'chunk_size':49152}
        self.q.downloads(FakeAPI())
        saved=next(m for m in self.q.pending()['messages'] if m['id']==-2)['files'][0]
        Path(saved['path']).write_bytes(b'changed')
        with self.assertRaises(BridgeError):self.q.begin(-2,'thread-one','baseline-turn',api=self.api)
        Path(saved['path']).write_bytes(data)
        self.assertEqual(self.q.begin(-2,'thread-one','baseline-turn',api=self.api)['files'][0]['sha256'],attachment['sha256'])

    def test_lost_receipt_response_recovers_after_restart_without_second_dispatch(self):
        state=domain.initial()
        state['items']['-1']={**self.item,'channel':'web','status':'approved','expires':2000,'lease_until':1120}
        class InterruptedAPI:
            def call(self,path,body):
                domain.receipt(state,body,1001)
                raise BridgeError('Response lost after remote commit')
        with self.assertRaises(BridgeError):self.q.receipts(InterruptedAPI())
        self.assertEqual(state['items']['-1']['status'],'delivered')
        self.assertEqual(self.q.pending()['messages'],[])
        self.q.db.close();self.q=Queue(Path(self.temp.name))
        class RecoveredAPI:
            def call(self,path,body):
                domain.receipt(state,body,1200)
                return {'status':'delivered'}
        self.q.receipts(RecoveredAPI())
        self.q.begin(-1,'thread-one','baseline-turn',api=self.api)
        with self.assertRaises(BridgeError):self.q.begin(-1,'thread-one','baseline-turn',api=self.api)

    def test_lost_publish_response_retries_same_revision_after_restart(self):
        self.receipt();dispatch=self.q.begin(-1,'thread-one','baseline-turn',api=self.api);self.q.sent(-1,dispatch['marker'])
        self.q.publish(-1,{'marker':dispatch['marker'],'thread':'thread-one','turn_id':'new-turn',
                          'status':'completed','events':[{'type':'agent_message','text':'Actual reply'}]})
        with self.q.db:self.q.db.execute("INSERT OR REPLACE INTO metadata VALUES('login_keys',?)",(int(time.time()),))
        state=domain.initial();state['items']['-1']={**self.item,'channel':'web','status':'delivered'}
        revisions=[]
        class RemoteAPI:
            fail=True
            def call(self,path,body):
                if path=='/v2/inbox/claim':return {'message':None}
                if path=='/v2/responses':
                    revisions.append(body['revision'])
                    result=workspace.publish(state,body,1001)
                    if self.fail:raise BridgeError('Response lost after remote commit')
                    return result
                raise AssertionError(path)
        api=RemoteAPI()
        with self.assertRaises(BridgeError):self.q.tick(api)
        self.q.db.close();self.q=Queue(Path(self.temp.name));api.fail=False
        self.q.tick(api)
        self.assertEqual(revisions,[1,1])
        self.assertEqual(state['items']['-1']['result_revision'],1)
        self.assertEqual(len(state['items']['-1']['events']),1)
        self.assertEqual(self.q.status()['counts'],[{'status':'complete','count':1}])

    def test_corrupt_download_never_becomes_a_dispatchable_file(self):
        data=b'wrong bytes'
        item={**self.item,'id':-2,'attachments':[{'id':'b'*32,'name':'test.log','size':len(data),'sha256':'0'*64}]}
        self.q.receive(item);self.receipt()
        class FakeAPI:
            def call(self,path,body):return {'data':base64.b64encode(data).decode()}
        with self.assertRaises(BridgeError):self.q.downloads(FakeAPI())
        pending=next(m for m in self.q.pending()['messages'] if m['id']==-2)
        self.assertEqual(pending['local_status'],'files_pending')
        self.assertEqual(list((Path(self.temp.name)/'attachments'/'-2').iterdir()),[])


if __name__ == '__main__': unittest.main()


class WaitTests(unittest.TestCase):
    def test_wait_returns_pending_work_without_dispatch(self):
        from web_client import wait_for_request
        from unittest.mock import Mock
        queue=Mock();queue.pending.return_value={'messages':[{'id':-3}],'trust':'external'}
        self.assertEqual(wait_for_request(queue,object())['status'],'ready')
        queue.begin.assert_not_called();queue.sent.assert_not_called()
    def test_wait_sleeps_and_returns_empty_timeout(self):
        from web_client import wait_for_request
        from unittest.mock import Mock,patch
        queue=Mock();queue.pending.return_value={'messages':[]}
        with patch('web_client.time.monotonic',side_effect=[0,0,2]),patch('web_client.time.sleep') as sleep:
            self.assertEqual(wait_for_request(queue,object(),2,1),{'status':'timeout','messages':[]})
            sleep.assert_called_once_with(1)
