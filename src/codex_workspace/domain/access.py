"""Authoritative workspace access and approval policy, without external I/O.

Task denies override member task and project grants. Owners see every task;
read-only tasks remain readable but cannot receive requests, even from owners.
Call mutations inside the same transaction as request handling.
"""
from . import domain


class Forbidden(Exception):
    pass


def is_owner(state, uid, owner):
    if uid not in state['bindings'].values():
        raise Forbidden()
    return state['bindings'].get(owner) == uid


def permitted_threads(state, uid, owner):
    catalog = state.get('catalog', {})
    if is_owner(state, uid, owner):
        return catalog
    grants = state.get('thread_grants', {}).get(str(uid), [])
    projects = state.get('project_grants', {}).get(str(uid), [])
    denied = state.get('thread_denies', {}).get(str(uid), [])
    return {key: value for key, value in catalog.items()
            if key not in denied and (key in grants or value.get('project_id') in projects)}


def set_grants(state, uid, owner, body):
    if not is_owner(state, uid, owner):
        raise Forbidden()
    target, threads = body.get('user_id'), body.get('threads')
    projects = body.get('projects', state.get('project_grants', {}).get(str(target), []))
    denied = body.get('denied_threads', state.get('thread_denies', {}).get(str(target), []))
    if (type(target) is not int or target not in state['bindings'].values() or target == uid
            or not isinstance(threads, list) or not all(isinstance(t,str) and t in state.get('catalog', {}) for t in threads)
            or not isinstance(projects,list) or not all(isinstance(p,str) and p in state.get('projects',{}) for p in projects)
            or not isinstance(denied,list) or not all(isinstance(t,str) and t in state.get('catalog',{}) for t in denied)):
        raise domain.Rejected('Invalid grant')
    state.setdefault('thread_grants', {})[str(target)] = list(dict.fromkeys(threads))
    state.setdefault('project_grants', {})[str(target)] = list(dict.fromkeys(projects))
    state.setdefault('thread_denies', {})[str(target)] = list(dict.fromkeys(denied))
    allowed=permitted_threads(state,target,owner)
    for item in state['items'].values():
        if item.get('channel') == 'web' and item['sender'] == target and item['thread'] not in allowed and item['status'] in ('approved', 'awaiting_approval'):
            item['status'] = 'target_unavailable'
    return {'ok': True}


def requires_approval(state, uid, owner):
    return not is_owner(state, uid, owner) and state.get('member_policies', {}).get(str(uid), {}).get('requires_approval', True) is not False


def set_member_policy(state, uid, owner, body):
    if not is_owner(state, uid, owner):
        raise Forbidden()
    target, required = body.get('user_id'), body.get('requires_approval')
    if type(target) is not int or target not in state['bindings'].values() or target == uid or type(required) is not bool:
        raise domain.Rejected('Invalid member policy')
    state.setdefault('member_policies', {})[str(target)] = {'requires_approval': required}
    # Policy applies to new requests; existing decisions and pending requests remain explicit.
    return {'ok': True}


def can_submit(state, uid, owner, thread):
    target = permitted_threads(state, uid, owner).get(thread)
    return target is not None and not target.get('read_only', False)
