"""History/catalog publisher for encrypted installations. No legacy passthrough."""
import hashlib
import time
from runtime_support import BridgeError
from sealed_channel import SealedChannel


class EncryptedHistoryAPI:
    def __init__(self, raw, vault):
        self.titles={}
        self.url=raw.url
        self.vault=vault
        self.channel=SealedChannel(raw,vault)
        self.vault.scope_key('workspace')

    def call(self,path,body):
        if path=='/v2/history/pending':
            # Server hints cannot choose local paths or cause plaintext reads.
            return {'threads':[]}
        if path=='/v2/catalog':
            self.titles={t['id']:t.get('title','Codex Workspace') for t in body['threads']}
            for thread in body['threads']:
                if thread['id'].startswith('device:') or thread['id']=='workspace':
                    raise BridgeError('Reserved encrypted scope')
                self.vault.scope_key(thread['id'])
            # Per-item records avoid large catalogs exceeding envelope limits.
            for project in body.get('projects',[]):
                ident=hashlib.sha256(project['id'].encode()).hexdigest()
                self.channel.snapshot('workspace','catalog','project:'+ident,project)
            for thread in body['threads']:
                self.channel.snapshot('workspace','catalog','task:'+thread['id'],thread)
            return self.channel.snapshot('workspace','catalog','index',{
                'projects':[p['id'] for p in body.get('projects',[])],
                'threads':[t['id'] for t in body['threads']],'updated_at':int(time.time())})
        if path=='/v2/history/publish':
            scope=body['thread']
            self.vault.active_key(scope)
            for message in body['messages']:
                ident=hashlib.sha256(message['id'].encode()).hexdigest()
                self.channel.snapshot(scope,'history',ident,message)
                if message.get('role')=='assistant' and message.get('phase')=='final_answer' and message.get('turn_id'):
                    from sealed_push import publish
                    publish(self.channel,scope,'answer:'+message['turn_id'],self.titles.get(scope,'Codex Workspace'),message['text'],message['created'])
            if body.get('finish'):
                self.channel.snapshot(scope,'history','checkpoint',
                    {**{k:v for k,v in body.items() if k!='messages'},'synced_at':int(time.time())})
            return {'ok':True}
        if path=='/v2/usage':
            return self.channel.snapshot('workspace','catalog','quota',body)
        raise BridgeError('Plaintext history API disabled in encrypted mode')
