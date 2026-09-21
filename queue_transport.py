"""Outbound receipts, claims and response publication; no CLI execution."""
import json
import time
from workspace_client import Conflict


def receipts(queue, api):
    for row in queue.db.execute("SELECT * FROM requests WHERE status='receiving'").fetchall():
        item = json.loads(row['payload'])
        try:
            api.call('/v2/inbox/ack', {'id': item['id'], 'lease': item['lease']})
        except Conflict:
            # Leave receiving until a new lease is claimed; never dispatch.
            continue
        with queue.db:
            queue.db.execute("UPDATE requests SET status='pending' WHERE id=?", (item['id'],))


def publish_results(queue, api):
    for row in queue.db.execute("SELECT * FROM requests WHERE status='publishing'").fetchall():
        result = json.loads(row['result'])
        api.call('/v2/responses', result)
        status = 'complete' if result['status'] in ('completed', 'failed') else 'dispatched'
        with queue.db:
            queue.db.execute('UPDATE requests SET status=? WHERE id=?', (status, row['id']))


def tick(queue, api):
    publish_results(queue, api)
    refreshed = queue.db.execute("SELECT value FROM metadata WHERE name='login_keys'").fetchone()
    key_status = 'fresh'
    if not refreshed or refreshed['value'] < time.time() - 3600:
        from cloud.login import public_keys
        try:
            # Fixed official HTTPS URL with certificate checks and no redirects.
            keys = public_keys(refresh=True)
            now = int(time.time())
            api.call('/v2/login-keys', {'keys':keys, 'fetched_at':now})
            with queue.db:
                queue.db.execute("INSERT OR REPLACE INTO metadata VALUES('login_keys',?)",(now,))
        except Exception:
            key_status = 'refresh_failed'
    queue.receipts(api)
    for _ in range(10):
        item = api.call('/v2/inbox/claim', {})['message']
        if item is None:
            break
        queue.receive(item)
        queue.receipts(api)
    queue.downloads(api)
    return {**queue.status(), 'login_keys':key_status}
