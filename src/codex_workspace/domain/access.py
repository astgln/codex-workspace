"""Single-account authorization and task availability."""
class Forbidden(Exception):
    pass


def is_owner(state, uid, owner):
    if type(uid) is not int or state.get('bindings', {}).get(owner) != uid:
        raise Forbidden()
    return True


def permitted_threads(state, uid, owner):
    is_owner(state, uid, owner)
    return state.get('catalog', {})


def can_submit(state, uid, owner, thread):
    try:
        target = permitted_threads(state, uid, owner).get(thread)
    except Forbidden:
        return False
    return target is not None and not target.get('read_only', False)
