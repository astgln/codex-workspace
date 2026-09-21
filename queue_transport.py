"""Outbound receipts, claims and response publication; no CLI execution."""
import json
from workspace_client import Conflict
from cloud.redaction import response_body


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
        api.call('/v2/responses', response_body(result))
        status = 'complete' if result['status'] in ('completed', 'failed') else 'dispatched'
        with queue.db:
            queue.db.execute('UPDATE requests SET status=? WHERE id=?', (status, row['id']))


def tick(queue, api):
    publish_results(queue, api)
    queue.receipts(api)
    for _ in range(10):
        item = api.call('/v2/inbox/claim', {})['message']
        if item is None:
            break
        queue.receive(item)
        queue.receipts(api)
    queue.downloads(api)
    return queue.status()
