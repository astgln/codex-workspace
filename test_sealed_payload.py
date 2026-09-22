import hashlib
import json
from test_sealed_channel import SealedChannelTests
from sealed_payload import publish
from server import opaque
from workspace_crypto import Context,decode,open_envelope

class PayloadTests(SealedChannelTests):
    def test_large_unicode_response_roundtrip_and_retry(self):
        value={'text':'Большой ответ 👋 '*20000}
        publish(self.channel,'task','answer',1,value)
        publish(self.channel,'task','answer',1,value)
        reply=opaque.read(self.remote,{'workspace':self.vault.workspace,'scope':'task','kind':'response','after':0},browser=True)
        entries=[]
        while True:
            entries.extend(reply['records'])
            if not reply['more']:break
            reply=opaque.read(self.remote,{'workspace':self.vault.workspace,'scope':'task','kind':'response','after':reply['after']},browser=True)
        values={e['envelope']['context'][3]:json.loads(open_envelope(decode(self.current['key'],maximum=32),self.vault.authority.public_key(),Context(*e['envelope']['context']),e['envelope'])) for e in entries}
        manifest=values['answer'];raw=b''.join(decode(values[part]['data'],maximum=48*1024) for part in manifest['parts'])
        self.assertEqual(json.loads(raw),value)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest['sha256'])
        self.assertEqual(len(raw),manifest['size'])
