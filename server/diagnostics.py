"""Owner-only operational counters; never include content or credentials."""
from contextlib import closing
import time
from cloud.access import Forbidden, is_owner
from .migrations import read_state


def inspect(store, uid, owner):
    with closing(store.connect()) as db:
        db.execute('BEGIN')
        state = read_state(db)
        if not is_owner(state, uid, owner):
            raise Forbidden()
        now = int(time.time())
        statuses = ('awaiting_approval','approved','delivered','rejected','expired','target_unavailable','superseded')
        queue = {status: 0 for status in statuses}
        for item in state.get('items', {}).values():
            if item.get('channel') == 'web' and item.get('status') in queue:
                queue[item['status']] += 1
        completed = sum(item.get('result_status') == 'completed' for item in state.get('items', {}).values())
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        notifications = {'devices':0,'retrying':0,'uncertain':0}
        if 'push_subscriptions' in tables:
            notifications['devices'] = db.execute('SELECT count(*) FROM push_subscriptions').fetchone()[0]
        if 'push_deliveries' in tables:
            notifications['retrying'] = db.execute('SELECT count(*) FROM push_deliveries WHERE done=0 AND attempts<8').fetchone()[0]
            notifications['uncertain'] = db.execute('SELECT count(*) FROM push_deliveries WHERE done=2').fetchone()[0]
        history = db.execute('SELECT max(synced) FROM history_threads').fetchone()[0] if 'history_threads' in tables else None
        seen = state.get('collector_seen')
        return {'observed_at':now, 'schema':db.execute('PRAGMA user_version').fetchone()[0],
                'collector_seen':seen, 'collector_recent':isinstance(seen,(int,float)) and 0<=now-seen<600,
                'catalog_updated':state.get('catalog_updated'), 'history_synced':history,
                'worker':state.get('worker_status'), 'queue':queue, 'completed':completed, 'notifications':notifications}
