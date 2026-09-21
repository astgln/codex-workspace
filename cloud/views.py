"""Single-account workspace projection."""
from . import domain
from .access import permitted_threads
from .requests import public_item


def view(state, uid, owner, now):
    catalog = permitted_threads(state, uid, owner)
    domain.cleanup(state, now)
    return {'user': {'id': uid}, 'threads': list(catalog.values()),
            'projects': list(state.get('projects', {}).values()),
            'weekly_quota': state.get('weekly_quota'),
            'catalog_updated': state.get('catalog_updated'),
            'collector_seen': state.get('collector_seen'),
            'messages': [public_item(item) for item in state['items'].values()
                         if item.get('channel') == 'web' and item['sender'] == uid]}
