import tempfile
import unittest
from server.store import Store
from server.diagnostics import inspect
from cloud.access import Forbidden


class DiagnosticsTests(unittest.TestCase):
    def test_only_owner_sees_counters_not_content(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            store.mutate(lambda state:state.update(bindings={'owner':1,'member':2},
                items={'-1':{'channel':'web','status':'queued','text':'secret-message','lease':'secret-lease'}}))
            result=inspect(store,1,'owner')
            self.assertEqual(result['queue']['queued'],1)
            self.assertNotIn('secret',str(result))
            self.assertFalse(result['collector_recent'])
            for uid in (2,3):
                with self.assertRaises(Forbidden):inspect(store,uid,'owner')
