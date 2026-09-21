"""Durable request lifecycle; no external I/O in transactions."""
import secrets

REQUEST_TTL = 86400
RETENTION = 7 * 86400
MAX_ITEMS = 200


class Rejected(Exception):
    pass


def initial():
    return {'bindings': {}, 'items': {}, 'seen': {}}


def cleanup(state, now):
    state['seen'] = {k:v for k,v in state.get('seen', {}).items() if v > now - RETENTION}
    state['items'] = {k:v for k,v in state['items'].items() if v['created'] > now - RETENTION}
    for item in state['items'].values():
        if item['status'] == 'queued' and item['expires'] <= now:
            item['status'] = 'expired'


def receipt(state, body, now):
    item = state['items'].get(str(body.get('id')))
    if not item or not secrets.compare_digest(item.get('lease', ''), str(body.get('lease', ''))) or not item.get('lease'):
        raise Rejected('Invalid receipt')
    if item['status'] == 'delivered':
        return
    if item['status'] != 'queued' or item['expires'] <= now or item.get('lease_until', 0) <= now:
        raise Rejected('Receipt expired')
    item['status'] = 'delivered'
    item['delivered_at'] = now
