"""Opaque browser sessions: HttpOnly cookies, per-session CSRF and revocation."""
import hashlib
import secrets
import time
from codex_workspace.domain import workspace

COOKIE='__Host-workspace-session'
TTL=8*3600


def connection(store):
    db=store.connect()
    db.execute('CREATE TABLE IF NOT EXISTS browser_sessions(digest TEXT PRIMARY KEY,uid INTEGER NOT NULL,csrf TEXT NOT NULL,expires INTEGER NOT NULL,created INTEGER NOT NULL)')
    if 'device' not in {row[1] for row in db.execute('PRAGMA table_info(browser_sessions)')}:
        db.execute('ALTER TABLE browser_sessions ADD COLUMN device TEXT')
    db.commit()
    return db


def issue(store,uid,device=None):
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32);now=int(time.time())
    db=connection(store)
    try:
        with db:
            db.execute('DELETE FROM browser_sessions WHERE expires<=?',(now,))
            db.execute('INSERT INTO browser_sessions(digest,uid,csrf,expires,created,device) VALUES(?,?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,csrf,now+TTL,now,device))
            # Bound abandoned sessions without evicting the new browser session.
            db.execute('DELETE FROM browser_sessions WHERE uid=? AND digest NOT IN (SELECT digest FROM browser_sessions WHERE uid=? ORDER BY created DESC,rowid DESC LIMIT 20)',(uid,uid))
    finally:db.close()
    return token,csrf


def verify(store,token):
    if not isinstance(token,str) or not 32<=len(token)<=128:raise workspace.Unauthorized()
    db=connection(store)
    try:row=db.execute('SELECT uid,csrf,expires,device FROM browser_sessions WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    finally:db.close()
    if not row or row[2]<=time.time():raise workspace.Unauthorized()
    from .device_auth import identity
    if not row[3]: raise workspace.Unauthorized()
    device,_=identity(store,row[3])
    if device['uid']!=row[0]:raise workspace.Unauthorized()
    return row[0],row[1]


def revoke(store,token):
    db=connection(store)
    try:
        with db:db.execute('DELETE FROM browser_sessions WHERE digest=?',(hashlib.sha256(token.encode()).hexdigest(),))
    finally:db.close()


def check_csrf(request,csrf,origin):
    if request.headers.get('origin')!=origin or not secrets.compare_digest(request.headers.get('x-csrf-token',''),csrf):
        raise workspace.Forbidden()


def upgrade_auth_trust(store):
    from .migrations import read_state, write_state
    db = store.connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS security_upgrades(name TEXT PRIMARY KEY)')
        if not db.execute("SELECT 1 FROM security_upgrades WHERE name='server-only-jwks-v2'").fetchone():
            state = read_state(db)
            state.pop('login_jwks', None)
            state.pop('telegram_jwks_v2', None)
            write_state(db, state)
            for table in ('browser_sessions', 'push_subscriptions', 'push_deliveries'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    db.execute('DELETE FROM ' + table)
            db.execute("INSERT INTO security_upgrades VALUES('server-only-jwks-v2')")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
