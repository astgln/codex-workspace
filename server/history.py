"""Shared public conversation history, separate from the bounded request queue."""
import json
import re
import time
from cloud import domain, workspace
from server.migrations import read_state
from server import push_preview
from cloud.redaction import public_text


def handle(store, uid, owner, action, body, collector=False):
    now=int(time.time())
    db=store.connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        push_preview.initialize(db)
        db.execute('CREATE TABLE IF NOT EXISTS push_answers(id TEXT PRIMARY KEY,thread TEXT,created INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS history_threads(thread TEXT PRIMARY KEY,cursor TEXT,synced INTEGER NOT NULL DEFAULT 0,requested INTEGER NOT NULL DEFAULT 0,more INTEGER NOT NULL DEFAULT 1)')
        db.execute('CREATE TABLE IF NOT EXISTS history_messages(thread TEXT NOT NULL,id TEXT NOT NULL,position TEXT NOT NULL,role TEXT NOT NULL,text TEXT NOT NULL,created INTEGER NOT NULL,PRIMARY KEY(thread,id))')
        db.execute('CREATE INDEX IF NOT EXISTS history_order ON history_messages(thread,position)')
        state=read_state(db)
        catalog=state.get('catalog',{})
        if action=='pending' and collector:
            rows=db.execute('SELECT thread,cursor,synced,more FROM history_threads WHERE requested>synced ORDER BY requested LIMIT 10').fetchall()
            result={'threads':[{'thread':r[0],'cursor':r[1],'synced':r[2],'more':bool(r[3])} for r in rows if r[0] in catalog]}
        else:
            thread=body.get('thread')
            if not isinstance(thread,str) or thread not in (catalog if collector else workspace.permitted_threads(state,uid,owner)):
                raise workspace.Forbidden()
            db.execute('INSERT OR IGNORE INTO history_threads(thread) VALUES(?)',(thread,))
            if action=='read' and not collector:
                before=body.get('before')
                if before is not None and (not isinstance(before,str) or len(before)>200):raise domain.Rejected('Invalid history cursor')
                meta=db.execute('SELECT cursor,synced,requested,more FROM history_threads WHERE thread=?',(thread,)).fetchone()
                if meta[1]<now-30:
                    db.execute('UPDATE history_threads SET requested=? WHERE thread=?',(now,thread))
                rows=db.execute('SELECT id,position,role,text,created FROM history_messages WHERE thread=? AND (? IS NULL OR position<?) ORDER BY position DESC LIMIT 51',(thread,before,before)).fetchall()
                page=rows[:50]
                result={'messages':[{**dict(zip(('id','position','role','text','created'),r)), 'text':public_text(r[3])} for r in reversed(page)],
                        'before':page[-1][1] if len(rows)>50 else None,'synced_at':meta[1] or None,
                        'loading_older':bool(meta[3]),'pending':meta[2]>meta[1] or meta[1]<now-30}
            elif action=='publish' and collector:
                messages=body.get('messages')
                if not isinstance(messages,list) or len(messages)>100:raise domain.Rejected('Invalid history batch')
                for message in messages:
                    if not isinstance(message,dict):raise domain.Rejected('Invalid history message')
                    ident,position,role,text,created=(message.get(k) for k in ('id','position','role','text','created'))
                    if (not isinstance(ident,str) or not 1<=len(ident)<=160 or not isinstance(position,str) or not 1<=len(position)<=200
                            or role not in ('user','assistant') or not isinstance(text,str) or not 1<=len(text)<=32000
                            or type(created) is not int or created<0):raise domain.Rejected('Invalid public history message')
                    text = public_text(text)
                    turn = message.get('turn_id')
                    if turn is not None and (not isinstance(turn,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',turn)):
                        raise domain.Rejected('Invalid history turn')
                    if role=='assistant' and message.get('phase')=='final_answer' and now-300<=created<=now+60:
                        event = 'answer:'+thread+':'+turn if turn else 'history:'+thread+':'+ident
                        db.execute('INSERT OR IGNORE INTO push_answers VALUES(?,?,?)',(event,thread,created))
                        push_preview.record(db,event,text)
                    db.execute('INSERT INTO history_messages VALUES(?,?,?,?,?,?) ON CONFLICT(thread,id) DO UPDATE SET position=excluded.position,role=excluded.role,text=excluded.text,created=excluded.created',(thread,ident,position,role,text,created))
                if body.get('finish'):
                    cursor=body.get('cursor')
                    if cursor is not None and (not isinstance(cursor,str) or len(cursor)>10000):raise domain.Rejected('Invalid source cursor')
                    if type(body.get('more')) is not bool or body['more'] and not cursor:raise domain.Rejected('Invalid source pagination')
                    # A latest-page refresh must not replace the cursor for older pages.
                    mode=body.get('mode')
                    if mode not in ('latest','older'):raise domain.Rejected('Invalid sync mode')
                    current=db.execute('SELECT cursor,synced FROM history_threads WHERE thread=?',(thread,)).fetchone()
                    if mode=='older' or current[1]==0:
                        db.execute('UPDATE history_threads SET cursor=?,more=? WHERE thread=?',(cursor,int(body['more']),thread))
                    db.execute('UPDATE history_threads SET synced=? WHERE thread=?',(now,thread))
                result={'ok':True,'count':len(messages)}
            else:
                raise workspace.Forbidden()
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
