"""Encrypted adapter for the existing CLI dispatch/recovery state machine."""
import json
from device_trust import ReplayError
from runtime_support import BridgeError
from sealed_channel import SealedChannel
from sealed_queue import SealedQueue
from workspace_crypto import CryptoError, encode


class SealedRuntime:
    def __init__(self, directory, vault, api, catalog):
        self.sealed = SealedQueue(directory, vault)
        self.queue = self.sealed.queue
        self.db, self.state = self.queue.db, self.queue.state
        self.channel = SealedChannel(api, vault)
        self.api = EncryptedWorkerAPI(self, api)
        self.catalog_scopes={t['id'] for t in catalog['threads']}
        self.titles={t['id']:t.get('title','Codex Workspace') for t in catalog['threads']}
        self.scopes = {t['id'] for t in catalog['threads'] if not t.get('read_only', False)}
        self.db.execute('CREATE TABLE IF NOT EXISTS encrypted_cursors (scope TEXT PRIMARY KEY, position INTEGER NOT NULL)')
        self.db.commit()

    def health(self,result):
        import time
        from worker_health import summary
        try:
            rows=self.db.execute("SELECT status,count(*) FROM requests WHERE json_type(payload,'$.encrypted_envelope')='object' GROUP BY status").fetchall()
            counts=dict(rows)
            waiting={item['id']:item['reason'] for item in result.get('requests',[])
                     if item.get('reason') in ('desktop_writer_lock','task_settings_unavailable')}
            for row in self.db.execute("SELECT id,payload FROM requests WHERE status='pending'").fetchall():
                item=json.loads(row['payload'])
                if not isinstance(item.get('encrypted_envelope'),dict):continue
                self.channel.snapshot(item['thread'],'response','dispatch:'+item['request_id'],{
                    'reason':waiting.get(row['id']), 'observed_at':int(time.time())})
            self.channel.snapshot('workspace','catalog','worker',{
                'worker':{**summary(result),'observed_at':int(time.time())},
                'queue':{'queued':counts.get('pending',0)},
                'completed':counts.get('complete',0)})
        except (BridgeError,OSError,ValueError,KeyError):pass

    def close(self):
        self.sealed.__exit__(None, None, None)

    def pending(self):
        result = self.queue.pending()
        # A mode transition never executes unencrypted backlog through this adapter.
        result['messages'] = [m for m in result['messages'] if isinstance(m.get('encrypted_envelope'), dict)]
        return result

    def begin(self, ident, thread, baseline, *, api):
        if api is not self.api or thread not in self.scopes:
            raise CryptoError('Encrypted execution context mismatch')
        return self.sealed.begin(ident, thread, baseline)

    def sent(self, *args):
        return self.queue.sent(*args)

    def publish(self, *args):
        return self.queue.publish(*args)

    def status(self):
        return self.queue.status()

    def tick(self):
        from queue_transport import publish_results
        from device_keys import DeviceKeys
        delivery=DeviceKeys(self.channel.vault,self.sealed.trust,self.channel)
        delivery.sync_owner_scopes(self.catalog_scopes)
        delivery.publish()
        from device_control import DeviceControl
        DeviceControl(self.channel.vault,self.sealed.trust,self.channel).tick(self.catalog_scopes)
        publish_results(self, self.api)
        for scope in sorted(self.scopes):
            # Scope keys must have been provisioned locally before the loop starts.
            row = self.db.execute('SELECT position FROM encrypted_cursors WHERE scope=?', (scope,)).fetchone()
            cursor = row[0] if row else 0
            page = self.channel.requests(scope, cursor)
            for entry in page['records']:
                try:
                    self.sealed.receive(scope, entry)
                except ReplayError:
                    # The queue commit may precede cursor commit after a crash.
                    # Skip only the exact locally persisted envelope, never a new
                    # ciphertext reusing the same nonce or server-controlled ID.
                    record = entry['envelope']['context'][3]
                    saved = self.db.execute("SELECT payload FROM requests WHERE json_extract(payload,'$.request_id')=?", (record,)).fetchall()
                    if len(saved) != 1 or json.loads(saved[0]['payload']).get('encrypted_envelope') != entry['envelope']:
                        raise
                with self.db:
                    self.db.execute('INSERT INTO encrypted_cursors VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET position=excluded.position',
                                    (scope, entry['sequence']))
        for row in self.db.execute("SELECT id,payload,files FROM requests WHERE status='pending'").fetchall():
            item = json.loads(row['payload'])
            if (isinstance(item.get('encrypted_envelope'), dict) and item['thread'] in self.scopes
                    and item.get('attachments') and not json.loads(row['files'])):
                self.sealed.download_files(self.channel.api, row['id'])
            if isinstance(item.get('encrypted_envelope'),dict) and item['thread'] in self.scopes:
                self.api.call('/v2/responses',{'id':item['id'],'thread':item['thread'],'revision':0,'status':'queued','events':[]})
        return self.status()


class EncryptedWorkerAPI:
    """Only known worker output may leave the endpoint, always as ciphertext."""
    def __init__(self, runtime, raw):
        self.runtime, self.raw, self.url = runtime, raw, raw.url

    def call(self, path, body):
        if path != '/v2/responses':
            # Includes legacy claims/validation/catalog/status: no silent passthrough.
            raise BridgeError('Plaintext worker API disabled in encrypted mode')
        row = self.runtime.db.execute('SELECT payload FROM requests WHERE id=?', (body.get('id'),)).fetchone()
        if row is None:
            raise CryptoError('Encrypted response has no local request')
        item = json.loads(row['payload'])
        if not isinstance(item.get('encrypted_envelope'), dict) or item['thread'] != body.get('thread'):
            raise CryptoError('Encrypted response context mismatch')
        signer = self.runtime.sealed.trust.db.execute(
            'SELECT public_key FROM devices WHERE id=?', (item['encrypted_envelope']['signer'],)).fetchone()
        if signer is None:
            raise CryptoError('Response signer is unavailable locally')
        payload = {'request': {k: item[k] for k in ('thread', 'text', 'created', 'attachments')},
                   'attachment_signer': encode(signer['public_key']), 'result': body}
        from sealed_payload import publish as publish_payload
        result=publish_payload(self.runtime.channel,item['thread'],item['request_id'],body['revision']+1,payload)
        if body.get('status')=='completed':
            from sealed_push import publish
            text=next((event.get('text','') for event in reversed(body.get('events',[])) if event.get('type')=='agent_message'),'')
            # Persist the event timestamp with the request, so retries publish the
            # same preview instead of changing an already signed record.
            self.runtime.db.execute('CREATE TABLE IF NOT EXISTS encrypted_push_times (id INTEGER PRIMARY KEY,created INTEGER)')
            import time
            self.runtime.db.execute('INSERT OR IGNORE INTO encrypted_push_times VALUES(?,?)',(item['id'],int(time.time())))
            self.runtime.db.commit()
            stamp=self.runtime.db.execute('SELECT created FROM encrypted_push_times WHERE id=?',(item['id'],)).fetchone()[0]
            publish(self.runtime.channel,item['thread'],'answer:'+body.get('turn_id',item['request_id']),self.runtime.titles[item['thread']],text,stamp)
        return result

