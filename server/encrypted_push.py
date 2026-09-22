"""Deliver opaque previews. The relay never receives notification text or titles."""
import hashlib
import json
import time
from cloud import workspace
from . import opaque,push


def tick(store,owner,mode):
    now=int(time.time())
    state=store.mutate(lambda s:s.copy())
    with push.database(store) as db:
        opaque._initialize(db)
        rows=db.execute("SELECT record,revision,envelope,created FROM opaque_records WHERE workspace=? AND kind='push' AND created>?",
                        (mode['workspace'],now-86400)).fetchall()
        subscriptions=db.execute('SELECT id,uid,subscription,created FROM push_subscriptions').fetchall()
    for ident,uid,raw,sub_created in subscriptions:
        try:
            if not workspace.is_owner(state,uid,owner):continue
        except workspace.Forbidden:continue
        for record,revision,encoded,created in rows:
            if created<sub_created:continue
            envelope=json.loads(encoded)
            payload={'envelope':envelope}
            if len(json.dumps(payload,ensure_ascii=False).encode())>3800:continue
            event='encrypted:'+hashlib.sha256(json.dumps(envelope['context'][:4],separators=(',',':')).encode()).hexdigest()
            with push.database(store) as db:
                db.execute('BEGIN IMMEDIATE')
                receipt=db.execute('SELECT done FROM push_deliveries WHERE subscription=? AND event=?',(ident,event)).fetchone()
                if receipt:continue
                # A network timeout is uncertain. Never retry an uncertain push
                # automatically and produce a second notification on the device.
                db.execute('INSERT INTO push_deliveries VALUES(?,?,?,?,2)',(ident,event,1,now))
            fresh=store.mutate(lambda s:s.copy())
            try:
                if not workspace.is_owner(fresh,uid,owner):continue
            except workspace.Forbidden:continue
            with push.database(store) as db:
                if not db.execute('SELECT 1 FROM push_subscriptions WHERE id=? AND uid=?',(ident,uid)).fetchone():continue
            code=push.send(store,json.loads(raw),payload)
            with push.database(store) as db:
                db.execute('UPDATE push_deliveries SET done=? WHERE subscription=? AND event=?',(1 if code is not None else 2,ident,event))
                if code in (404,410):db.execute('DELETE FROM push_subscriptions WHERE id=?',(ident,))
