import json
from pathlib import Path
import tempfile
import unittest
from local_queue import Queue
from queue_transport import tick


class TransportTests(unittest.TestCase):
    def test_completed_response_published_before_failing_inbox(self):
        class API:
            def __init__(self):self.paths=[]
            def call(self,path,body):
                self.paths.append(path)
                if path=='/v2/responses':return {'ok':True}
                raise OSError('inbox unavailable')
        with tempfile.TemporaryDirectory() as folder, Queue(Path(folder)) as queue:
            with queue.db:
                queue.db.execute("INSERT INTO requests(id,payload,status,result) VALUES(-1,'{}','publishing',?)",
                                 (json.dumps({'id':-1,'status':'completed'}),))
                queue.db.execute("INSERT INTO metadata VALUES('login_keys',9999999999)")
            api=API()
            with self.assertRaises(OSError):tick(queue,api)
            self.assertEqual(api.paths,['/v2/responses','/v2/inbox/claim'])
            self.assertEqual(queue.db.execute('SELECT status FROM requests').fetchone()[0],'complete')
