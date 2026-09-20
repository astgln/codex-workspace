import base64
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from cloud import domain, workspace
from server import files
from server.store import Store


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.now=int(time.time())
        def setup(s):
            s['bindings']={'owner':10,'friend':20,'other':30}
            workspace.sync_catalog(s,{'project_id':'project','threads':[{'id':'thread-launcher','title':'Launcher','project_id':'project'}]},'project',self.now)
            workspace.set_grants(s,10,'owner',{'user_id':20,'threads':['thread-launcher']})
            workspace.set_grants(s,10,'owner',{'user_id':30,'threads':['thread-launcher']})
        self.store.mutate(setup)
        self.data=b'Example log\n'
        self.body={'thread':'thread-launcher','name':'Connection.log','size':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest(),'request_id':'upload-unique-key-1'}

    def tearDown(self):self.temp.cleanup()

    def upload(self):
        upload=files.handle(self.store,20,'owner','start',self.body)
        files.handle(self.store,20,'owner','chunk',{'id':upload['id'],'index':0,'data':base64.b64encode(self.data).decode()})
        files.handle(self.store,20,'owner','finish',{'id':upload['id']})
        return upload

    def test_immutable_file_bound_to_approved_request(self):
        upload=self.upload()
        with self.assertRaises(workspace.Forbidden):files.handle(self.store,10,'owner','get',{'id':upload['id'],'index':0})
        with self.assertRaises(workspace.Forbidden):files.handle(self.store,None,'owner','get',{'id':upload['id'],'index':0},True)
        item=self.store.mutate(lambda s:workspace.submit(s,20,'owner',{'thread':'thread-launcher','text':'','attachments':[upload['id']],'request_id':'message-unique-key'},self.now))
        self.assertEqual(item['attachments'][0]['sha256'],self.body['sha256'])
        files.handle(self.store,10,'owner','get',{'id':upload['id'],'index':0})
        shared=files.handle(self.store,30,'owner','get',{'id':upload['id'],'index':0})
        self.assertEqual(base64.b64decode(shared['data']),self.data)
        self.store.mutate(lambda s:workspace.set_grants(s,10,'owner',{'user_id':30,'threads':[]}))
        with self.assertRaises(workspace.Forbidden):files.handle(self.store,30,'owner','get',{'id':upload['id'],'index':0})
        with self.assertRaises(domain.Rejected):files.handle(self.store,20,'owner','chunk',{'id':upload['id'],'index':0,'data':base64.b64encode(self.data).decode()})
        self.store.mutate(lambda s:workspace.decision(s,10,'owner',{'id':item['id'],'decision':'approved','snapshot':item['snapshot']},self.now))
        claim=self.store.mutate(lambda s:workspace.collect(s,self.now,'owner'))
        self.store.mutate(lambda s:domain.receipt(s,claim,self.now))
        result=files.handle(self.store,None,'owner','get',{'id':upload['id'],'index':0},True)
        self.assertEqual(base64.b64decode(result['data']),self.data)

    def test_incomplete_and_wrong_digest_fail(self):
        upload=files.handle(self.store,20,'owner','start',{**self.body,'sha256':'0'*64})
        with self.assertRaises(domain.Rejected):files.handle(self.store,20,'owner','finish',{'id':upload['id']})
        files.handle(self.store,20,'owner','chunk',{'id':upload['id'],'index':0,'data':base64.b64encode(self.data).decode()})
        with self.assertRaises(domain.Rejected):files.handle(self.store,20,'owner','finish',{'id':upload['id']})

    def test_path_and_size_validation(self):
        for change in ({'name':'../file'},{'name':'a\\b'},{'size':files.MAX_FILE+1},{'size':0}):
            with self.assertRaises(domain.Rejected):files.handle(self.store,20,'owner','start',{**self.body,**change})
        with self.assertRaises(domain.Rejected):files.handle(self.store,20,'owner','get',{'id':'../file','index':0})

    def test_cleanup_removes_expired_bytes_and_metadata(self):
        upload=self.upload()
        self.store.mutate(lambda s:s['uploads'][upload['id']].update(expires=0))
        files.cleanup(self.store)
        self.assertFalse((Path(self.temp.name)/'uploads'/upload['id']).exists())
        self.assertEqual(self.store.mutate(lambda s:s['uploads']),{})


if __name__=='__main__':unittest.main()
