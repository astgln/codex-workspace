"""Endpoint-owned experimental ACL; the relay cannot widen cryptographic grants."""
import json
import hashlib
from codex_workspace.domain import access
from codex_workspace.crypto.workspace_crypto import CryptoError


class LocalAccess:
    def __init__(self,vault,trust):
        self.vault,self.trust=vault,trust
        trust.db.execute('CREATE TABLE IF NOT EXISTS encrypted_access (id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL)')
        trust.db.execute('CREATE TABLE IF NOT EXISTS encrypted_device_members (device TEXT PRIMARY KEY,uid INTEGER NOT NULL)')
        trust.db.execute('CREATE TABLE IF NOT EXISTS encrypted_decisions (request TEXT PRIMARY KEY,snapshot TEXT NOT NULL,signer TEXT NOT NULL,proof TEXT NOT NULL,created INTEGER NOT NULL)')
        vault.db.execute('CREATE TABLE IF NOT EXISTS acl_transition (id INTEGER PRIMARY KEY CHECK(id=1),plan TEXT NOT NULL)')

    def bootstrap(self,owner_uid,members):
        """Local migration only. Never expose bootstrap as a relay operation."""
        if type(owner_uid) is not int or owner_uid<=0 or not isinstance(members,list):raise CryptoError('Invalid local identities')
        bindings={'owner':owner_uid}
        for member in members:
            if (not isinstance(member,dict) or set(member)!={'id','username'} or type(member['id']) is not int
                    or member['id']<=0 or not isinstance(member['username'],str) or not member['username'] or member['username']=='owner'
                    or member['id'] in bindings.values() or member['username'] in bindings):raise CryptoError('Invalid local identities')
            bindings[member['username']]=member['id']
        value={'bindings':bindings,'thread_grants':{},'project_grants':{},'thread_denies':{},'member_policies':{},'items':{}}
        self.trust.db.execute('INSERT INTO encrypted_access VALUES(1,?)',(json.dumps(value),))

    def state(self,catalog):
        row=self.trust.db.execute('SELECT value FROM encrypted_access WHERE id=1').fetchone()
        if row is None:raise CryptoError('Local access policy is not initialized')
        value=json.loads(row['value'])
        value['catalog']={t['id']:t for t in catalog['threads']}
        value['projects']={p['id']:p for p in catalog['projects']}
        return value

    def identity(self,device,catalog):
        state=self.state(catalog)
        grant=self.trust.db.execute('SELECT scopes FROM device_grants WHERE device=?',(device,)).fetchone()
        trusted=self.trust.db.execute('SELECT revoked FROM devices WHERE id=?',(device,)).fetchone()
        if not grant or not trusted or trusted['revoked']:raise CryptoError('Untrusted endpoint identity')
        mapped=self.trust.db.execute('SELECT uid FROM encrypted_device_members WHERE device=?',(device,)).fetchone()
        if mapped:
            if 'workspace' in json.loads(grant['scopes']):raise CryptoError('Member has an invalid owner grant')
            uid=mapped['uid']
            if uid==state['bindings']['owner']:raise CryptoError('Owner cannot be a member')
        else:
            if 'workspace' not in json.loads(grant['scopes']):raise CryptoError('Device has no local account binding')
            uid=state['bindings']['owner']
        if uid not in state['bindings'].values():raise CryptoError('Unknown locally bound account')
        return uid,state

    def authorize(self,device,thread,catalog):
        uid,state=self.identity(device,catalog)
        if not access.can_submit(state,uid,'owner',thread):raise CryptoError('Task is not writable by this device')
        return {'sender':uid,'requires_approval':access.requires_approval(state,uid,'owner')}

    def prepare(self,device,action,body,catalog):
        self.vault.assert_ready()
        uid,state=self.identity(device,catalog)
        if not access.is_owner(state,uid,'owner'):raise CryptoError('Owner signature required')
        if action=='add-member':
            if not isinstance(body,dict) or set(body)!={'name'} or not isinstance(body['name'],str):raise CryptoError('Invalid member name')
            name=body['name'].strip()
            if not 1<=len(name)<=64 or any(ord(c)<32 for c in name) or name.casefold()=='owner':raise CryptoError('Invalid member name')
            existing=next((n for n in state['bindings'] if n.casefold()==name.casefold()),None)
            if existing is None:
                if len(state['bindings'])>=1000:raise CryptoError('Member limit reached')
                member_id=int.from_bytes(hashlib.sha256((self.vault.workspace+'\0'+name.casefold()).encode()).digest()[:6],'big')+1
                if member_id in state['bindings'].values():raise CryptoError('Account identifier collision')
                state['bindings'][name]=member_id
        elif action=='grants':access.set_grants(state,uid,'owner',body)
        elif action=='member-policy':access.set_member_policy(state,uid,'owner',body)
        else:raise CryptoError('Unsupported local policy action')
        self._prepare_state(state,catalog)

    def _prepare_state(self,state,catalog):
        db=self.trust.db
        grants={};rotate={}
        for row in db.execute('''SELECT devices.id,device_grants.scopes,encrypted_device_members.uid FROM devices
          JOIN device_grants ON devices.id=device_grants.device LEFT JOIN encrypted_device_members
          ON devices.id=encrypted_device_members.device WHERE devices.revoked=0'''):
            if row['uid'] is None:continue
            scopes=set(access.permitted_threads(state,row['uid'],'owner'))
            for scope in scopes:self.vault.scope_key(scope)
            previous=set(json.loads(row['scopes']))
            for scope in previous-scopes:
                if scope=='workspace' or scope.startswith('device:'):raise CryptoError('Invalid member key scope')
                rotate[scope]=self.vault.active_key(scope)['epoch']+1
            grants[row['id']]=sorted(scopes)
        persistent={k:v for k,v in state.items() if k not in ('catalog','projects')}
        plan={'state':persistent,'grants':grants,'rotate':rotate}
        self.vault.db.execute('INSERT INTO acl_transition VALUES(1,?)',(json.dumps(plan,sort_keys=True,separators=(',',':')),))

    def sync_catalog(self,catalog):
        self.vault.assert_ready()
        state=self.state(catalog)
        changed=False
        for row in self.trust.db.execute('''SELECT device_grants.scopes,encrypted_device_members.uid FROM devices
          JOIN device_grants ON devices.id=device_grants.device JOIN encrypted_device_members
          ON devices.id=encrypted_device_members.device WHERE devices.revoked=0'''):
            if set(json.loads(row['scopes']))!=set(access.permitted_threads(state,row['uid'],'owner')):changed=True;break
        if changed:self._prepare_state(state,catalog);self.reconcile()

    def reconcile(self):
        row=self.vault.db.execute('SELECT plan FROM acl_transition WHERE id=1').fetchone()
        if row is None:return False
        plan=json.loads(row['plan'])
        if not isinstance(plan,dict) or set(plan)!={'state','grants','rotate'}:raise CryptoError('Invalid local ACL transition')
        db=self.trust.db;db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('UPDATE encrypted_access SET value=? WHERE id=1',(json.dumps(plan['state']),))
            for device,scopes in plan['grants'].items():
                db.execute('UPDATE device_grants SET scopes=? WHERE device=?',(json.dumps(scopes,separators=(',',':')),device))
            for scope,target in plan['rotate'].items():
                current=self.vault.scope_key(scope)
                if current['epoch']<target:
                    if current['epoch']!=target-1:raise CryptoError('Local ACL rotation epoch changed')
                    self.vault.scope_key(scope,rotate=True)
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK');raise
        self.vault.db.execute('BEGIN IMMEDIATE')
        try:
            self.vault.db.execute('UPDATE identity SET revision=revision+1 WHERE id=1')
            self.vault.db.execute('DELETE FROM acl_transition')
            self.vault.db.execute('COMMIT')
        except BaseException:
            self.vault.db.execute('ROLLBACK');raise
        return True

    def decision(self,device,body,catalog,proof):
        import time
        uid,state=self.identity(device,catalog)
        if not access.is_owner(state,uid,'owner'):raise CryptoError('Owner signature required')
        if (not isinstance(body,dict) or set(body)!={'id','snapshot','decision'} or type(body['id']) is not int
                or not isinstance(body['snapshot'],str) or body['decision'] not in ('approved','rejected')):raise CryptoError('Invalid signed decision')
        row=self.trust.db.execute('SELECT payload,status FROM requests WHERE id=?',(body['id'],)).fetchone()
        if row is None or row['status']!='awaiting_approval':raise CryptoError('Request is no longer awaiting approval')
        item=json.loads(row['payload'])
        if item['snapshot']!=body['snapshot']:raise CryptoError('Approved request changed')
        if body['decision']=='approved':
            self.trust.db.execute('INSERT INTO encrypted_decisions VALUES(?,?,?,?,?)',
                                 (item['request_id'],item['snapshot'],device,json.dumps(proof),int(time.time())))
        self.trust.db.execute('UPDATE requests SET status=? WHERE id=?',('pending' if body['decision']=='approved' else 'rejected',body['id']))

    def check_decision(self,item,catalog):
        if not item.get('requires_approval'):return
        from codex_workspace.devices.device_keys import delivery_scope
        from codex_workspace.crypto.key_material import public_key
        from codex_workspace.crypto.workspace_crypto import Context,decode,encode,key_id,open_envelope
        row=self.trust.db.execute('SELECT * FROM encrypted_decisions WHERE request=?',(item['request_id'],)).fetchone()
        if row is None or row['snapshot']!=item['snapshot']:raise CryptoError('Owner approval required')
        uid,state=self.identity(row['signer'],catalog)
        if not access.is_owner(state,uid,'owner'):raise CryptoError('Approval device no longer trusted')
        public=self.trust.db.execute('SELECT public_key FROM devices WHERE id=?',(row['signer'],)).fetchone()[0]
        scope=delivery_scope(public);proof=json.loads(row['proof'])
        keys=[r['key'] for r in self.vault.db.execute('SELECT key FROM scope_keys WHERE scope=?',(scope,)) if key_id(r['key'])==proof.get('key_id')]
        if len(keys)!=1:raise CryptoError('Approval key unavailable')
        context=Context(self.vault.workspace,scope,'control',proof['context'][3],1)
        command=json.loads(open_envelope(keys[0],public_key(encode(public)),context,proof))
        if (command.get('action')!='decide' or command.get('args')!={'id':item['id'],'snapshot':item['snapshot'],'decision':'approved'}
                or not command['issued_at']<=row['created']+60 or not row['created']<command['expires_at']):
            raise CryptoError('Approval does not match this request')

    def publish(self,catalog,channel):
        """Publish only locally authorized views, separately encrypted per device."""
        from codex_workspace.devices.device_keys import delivery_scope
        import hashlib
        import time
        state=self.state(catalog)
        db=self.trust.db;db.execute('BEGIN IMMEDIATE')
        try:
            for row in db.execute('SELECT id,public_key FROM devices WHERE revoked=0').fetchall():
                uid,_=self.identity(row['id'],catalog)
                owner=access.is_owner(state,uid,'owner')
                allowed=access.permitted_threads(state,uid,'owner')
                scope=delivery_scope(row['public_key'])
                user={'id':uid,'role':'owner' if owner else 'member','requires_approval':access.requires_approval(state,uid,'owner')}
                members=[]
                if owner:
                    for name,ident in state['bindings'].items():
                        if ident==uid:continue
                        members.append({'id':ident,'username':name,'threads':state['thread_grants'].get(str(ident),[]),
                            'projects':state['project_grants'].get(str(ident),[]),'denied_threads':state['thread_denies'].get(str(ident),[]),
                            'requires_approval':access.requires_approval(state,ident,'owner')})
                channel.snapshot(scope,'catalog','access',{'user':user,'members':members})
                if owner:continue
                project_ids={t.get('project_id') for t in allowed.values()}
                projects=[p for p in catalog['projects'] if p['id'] in project_ids]
                for project in projects:
                    channel.snapshot(scope,'catalog','project:'+hashlib.sha256(project['id'].encode()).hexdigest(),project)
                for thread in allowed.values():channel.snapshot(scope,'catalog','task:'+thread['id'],thread)
                channel.snapshot(scope,'catalog','index',{'projects':[p['id'] for p in projects],'threads':list(allowed),
                    'updated_at':int(time.time())//30*30})
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK');raise
