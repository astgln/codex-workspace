"""Private Web Push subscriptions and durable, permission-checked delivery."""
from contextlib import contextmanager
import base64
import hashlib
import json
import os
import time
from urllib.parse import urlsplit
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from pywebpush import webpush, WebPushException
from cloud import workspace, domain


@contextmanager
def database(store):
    db=store.connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:db.close()


def initialize(store):
    key = store.directory/'vapid.pem'
    if not key.exists():
        raw=ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
    with database(store) as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS push_subscriptions(id TEXT PRIMARY KEY,uid INTEGER,subscription TEXT,created INTEGER);
        CREATE TABLE IF NOT EXISTS push_deliveries(subscription TEXT,event TEXT,attempts INTEGER,next_attempt INTEGER,done INTEGER,PRIMARY KEY(subscription,event));
        CREATE TABLE IF NOT EXISTS push_answers(id TEXT PRIMARY KEY,thread TEXT,created INTEGER);''')


def public_key(store):
    key=serialization.load_pem_private_key((store.directory/'vapid.pem').read_bytes(),None)
    return base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')


def endpoint_ok(endpoint):
    if not isinstance(endpoint,str) or len(endpoint)>2048:return False
    try:
        url=urlsplit(endpoint)
        return (url.scheme=='https' and url.port in (None,443) and not url.username and not url.password and not url.fragment
                and url.hostname in ('web.push.apple.com','fcm.googleapis.com','updates.push.services.mozilla.com') and url.path.startswith('/'))
    except ValueError:return False


def handle(store,uid,owner,action,body):
    state=store.mutate(lambda s:s.copy());workspace.is_owner(state,uid,owner)
    if action=='config':return {'public_key':public_key(store)}
    sub=body.get('subscription',{});endpoint=sub.get('endpoint') if isinstance(sub,dict) else None
    if not endpoint_ok(endpoint):raise domain.Rejected('Invalid push endpoint')
    ident=hashlib.sha256(endpoint.encode()).hexdigest()
    with database(store) as db:
        existing=db.execute('SELECT uid FROM push_subscriptions WHERE id=?',(ident,)).fetchone()
        if existing and existing[0]!=uid:raise workspace.Forbidden()
        if action=='unsubscribe':
            db.execute('DELETE FROM push_subscriptions WHERE id=? AND uid=?',(ident,uid));return {'ok':True}
        if action!='subscribe':raise domain.Rejected('Unknown push action')
        keys=sub.get('keys',{})
        try:
            auth=base64.urlsafe_b64decode(keys['auth']+'='*(-len(keys['auth'])%4))
            point=base64.urlsafe_b64decode(keys['p256dh']+'='*(-len(keys['p256dh'])%4))
            if len(auth)!=16 or len(point)!=65:raise ValueError()
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),point)
        except (KeyError,TypeError,ValueError):raise domain.Rejected('Invalid push keys') from None
        if not existing and db.execute('SELECT count(*) FROM push_subscriptions WHERE uid=?',(uid,)).fetchone()[0]>=10:
            raise domain.Rejected('Device limit')
        clean={'endpoint':endpoint,'keys':{'auth':keys['auth'],'p256dh':keys['p256dh']}}
        db.execute('INSERT INTO push_subscriptions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET subscription=excluded.subscription',(ident,uid,json.dumps(clean),int(time.time())))
    return {'ok':True}


class NoRedirect(requests.Session):
    def request(self,*args,**kwargs):
        kwargs['allow_redirects']=False
        return super().request(*args,**kwargs)


def send(store,sub,payload):
    if not endpoint_ok(sub['endpoint']):return 410
    with NoRedirect() as session:
        try:
            response=webpush(sub,json.dumps(payload),vapid_private_key=str(store.directory/'vapid.pem'),
                vapid_claims={'sub':os.environ['PUBLIC_ORIGIN']},ttl=3600,timeout=10,requests_session=session)
            return response.status_code
        except WebPushException as exc:
            return exc.response.status_code if exc.response is not None else 503
        except requests.RequestException:return 503


def tick(store,owner):
    now=int(time.time());state=store.mutate(lambda s:s.copy())
    events=[]
    for item in state['items'].values():
        if item.get('channel')!='web':continue
        if item['status']=='awaiting_approval' and item['expires']>now:
            events.append(('approval:'+str(item['id']),item['thread'],item['created'],'approval'))
        if item.get('result_status')=='completed':
            events.append(('reply:'+str(item['id']),item['thread'],item.get('result_updated',0),'answer'))
    with database(store) as db:
        events.extend((r[0],r[1],r[2],'answer') for r in db.execute('SELECT id,thread,created FROM push_answers WHERE created>?',(now-86400,)))
        subscriptions=db.execute('SELECT id,uid,subscription,created FROM push_subscriptions').fetchall()
        db.execute('DELETE FROM push_answers WHERE created<?',(now-86400,))
        db.execute('DELETE FROM push_deliveries WHERE next_attempt<?',(now-7*86400,))
    for ident,uid,raw,created in subscriptions:
        try:allowed=workspace.permitted_threads(state,uid,owner);admin=workspace.is_owner(state,uid,owner)
        except workspace.Forbidden:continue
        for event,thread,stamp,kind in events:
            if stamp<created or stamp<now-86400 or thread not in allowed or (kind=='approval' and not admin):continue
            with database(store) as db:
                row=db.execute('SELECT attempts,next_attempt,done FROM push_deliveries WHERE subscription=? AND event=?',(ident,event)).fetchone()
                if row and (row[2] or row[1]>now or row[0]>=8):continue
                attempts=(row[0] if row else 0)+1
                db.execute('INSERT OR REPLACE INTO push_deliveries VALUES(?,?,?,?,0)',(ident,event,attempts,now+120))
            # No task names, message bodies, files or approval credentials on lock screen.
            payload={'title':'Codex Workspace','body':'Новый запрос на одобрение' if kind=='approval' else 'Готов новый ответ',
                     'url':'/#approvals' if kind=='approval' else '/#thread='+thread,'tag':kind+':'+thread}
            fresh=store.mutate(lambda s:s.copy())
            try:
                if thread not in workspace.permitted_threads(fresh,uid,owner):continue
                if kind=='approval':
                    item=fresh['items'].get(event.split(':',1)[1])
                    if not item or item['status']!='awaiting_approval' or item['expires']<=int(time.time()):continue
            except workspace.Forbidden:continue
            with database(store) as db:
                if not db.execute('SELECT 1 FROM push_subscriptions WHERE id=? AND uid=?',(ident,uid)).fetchone():continue
            code=send(store,json.loads(raw),payload)
            with database(store) as db:
                db.execute('UPDATE push_deliveries SET done=?,next_attempt=? WHERE subscription=? AND event=?',
                           (int(200<=code<300 or code in (400,401,403,404,410)),now+min(3600,30*2**attempts),ident,event))
                if code in (404,410):db.execute('DELETE FROM push_subscriptions WHERE id=?',(ident,))
