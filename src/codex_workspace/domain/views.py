"""Permission-filtered workspace projection for browser clients."""
from . import domain
from .access import is_owner, permitted_threads, requires_approval
from .requests import public_item


def view(state, uid, owner, now):
    domain.cleanup(state, now)
    admin = is_owner(state, uid, owner)
    catalog = permitted_threads(state, uid, owner)
    result = {'user': {'id': uid, 'role': 'owner' if admin else 'member', 'requires_approval': requires_approval(state, uid, owner)},
              'threads': list(catalog.values()), 'catalog_updated': state.get('catalog_updated'),
              'collector_seen': state.get('collector_seen'), 'messages': [public_item(item) for item in state['items'].values()
                if item.get('channel') == 'web' and (admin or item['thread'] in catalog)]}
    visible_projects={t.get('project_id') for t in catalog.values()} | set(state.get('project_grants',{}).get(str(uid),[]))
    result['projects']=[p for p in state.get('projects',{}).values() if admin or p['id'] in visible_projects]
    result['weekly_quota'] = state.get('weekly_quota')
    if admin:
        result['members'] = [{'id': ident, 'username': name, 'requires_approval': requires_approval(state, ident, owner), 'projects':state.get('project_grants',{}).get(str(ident),[]), 'denied_threads':state.get('thread_denies',{}).get(str(ident),[]), 'threads': state.get('thread_grants', {}).get(str(ident), [])}
                             for name, ident in state['bindings'].items() if name != owner]
    return result
