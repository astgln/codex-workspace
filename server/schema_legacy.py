"""Read obsolete database layouts for one-way import only."""
import copy
import json
from cloud import domain
from . import catalog_store, request_store

def read_state(db):
    row = db.execute('SELECT value FROM mailbox WHERE id=1').fetchone()
    state = json.loads(row[0]) if row else domain.initial()
    for section, in db.execute('SELECT name FROM access_sections'):
        state[section] = {}
    for name, uid in db.execute('SELECT username,uid FROM member_bindings'):
        state['bindings'][name] = uid
    for kind, uid in db.execute('SELECT kind,uid FROM grant_subjects'):
        state[kind][uid] = []
    for kind, uid, target in db.execute('SELECT kind,uid,target FROM access_grants ORDER BY position'):
        state[kind][uid].append(target)
    for uid, required in db.execute('SELECT uid,requires_approval FROM member_policies'):
        state['member_policies'][uid] = {'requires_approval': bool(required)}
    if db.execute('PRAGMA user_version').fetchone()[0] >= 2:
        catalog_store.read(db, state)
    if db.execute('PRAGMA user_version').fetchone()[0] >= 3:
        request_store.read(db, state, historical=True)
    return state


def normalize(state):
    state = copy.deepcopy(state)
    for key in ('thread_grants', 'project_grants', 'thread_denies', 'member_policies'):
        state.pop(key, None)
    for item in state.get('items', {}).values():
        if item.get('status') == 'approved':
            item['status'] = 'queued'
        elif item.get('status') == 'awaiting_approval':
            item['status'] = 'expired'
        for key in ('card', 'reply', 'approved_by', 'decision_at', 'approval_source', 'nonce'):
            item.pop(key, None)
    return state


def drop_access(db):
    for table in ('access_grants', 'grant_subjects', 'member_bindings', 'member_policies', 'access_sections'):
        db.execute('DROP TABLE ' + table)
