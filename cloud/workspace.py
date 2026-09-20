"""Project-scoped web workspace and signed application sessions.

No Bot API calls, filesystem access or external I/O. Call state functions inside
one serializable transaction. A web session cannot act as a local collector.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
from . import domain

SESSION_TTL = 8 * 3600
MAX_TEXT = 16000


class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


def _session_key(bot_token):
    return hmac.new(bot_token.encode(), b'warcraft-web-session-v1', hashlib.sha256).digest()


def issue_session(user_id, bot_token, now):
    payload = base64.urlsafe_b64encode(json.dumps({'uid': user_id, 'exp': now + SESSION_TTL,
        'nonce': secrets.token_urlsafe(16)}, separators=(',', ':')).encode()).decode().rstrip('=')
    signature = hmac.new(_session_key(bot_token), payload.encode(), hashlib.sha256).hexdigest()
    return payload + '.' + signature


def verify_session(token, bot_token, now):
    try:
        if not isinstance(token, str) or len(token) > 1024:
            raise Unauthorized()
        payload, signature = token.split('.')
        actual = hmac.new(_session_key(bot_token), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, actual):
            raise Unauthorized()
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if type(claims['uid']) is not int or not now < claims['exp'] <= now + SESSION_TTL:
            raise Unauthorized()
        return claims['uid']
    except (ValueError, KeyError, TypeError):
        raise Unauthorized() from None


def bind_user(state, user, allowed):
    name = user['username']
    if name in allowed and name not in state['bindings']:
        state['bindings'][name] = user['id']
    if user['id'] not in state['bindings'].values():
        raise Forbidden()
    return user['id']


def is_owner(state, uid, owner):
    if uid not in state['bindings'].values():
        raise Forbidden()
    return state['bindings'].get(owner) == uid


def sync_catalog(state, body, project, now):
    if body.get('project_id') != project:
        raise Forbidden()
    entries = body.get('threads')
    if not isinstance(entries, list) or len(entries) > 100:
        raise domain.Rejected('Invalid catalog')
    catalog = {}
    for entry in entries:
        if (not isinstance(entry, dict) or not re.fullmatch(r'[a-zA-Z0-9-]{10,80}', str(entry.get('id', '')))
                or entry.get('project_id') != project or not isinstance(entry.get('title'), str)
                or not 1 <= len(entry['title']) <= 200):
            raise domain.Rejected('Invalid thread')
        if entry['id'] in catalog:
            raise domain.Rejected('Duplicate thread')
        catalog[entry['id']] = {'id': entry['id'], 'title': entry['title'],
            'status': entry.get('status') if entry.get('status') in ('active', 'idle', 'notLoaded') else 'unknown',
            'read_only': entry.get('read_only') is True}
    state['catalog'] = catalog
    state['catalog_updated'] = now
    # Revoking a target immediately stops every not-yet-delivered request to it.
    for item in state['items'].values():
        if item.get('channel') == 'web' and (item['thread'] not in catalog or catalog[item['thread']].get('read_only')) and item['status'] in ('approved', 'awaiting_approval'):
            item['status'] = 'target_unavailable'
    return {'count': len(catalog)}


def permitted_threads(state, uid, owner):
    catalog = state.get('catalog', {})
    if is_owner(state, uid, owner):
        return catalog
    grants = state.get('thread_grants', {}).get(str(uid), [])
    return {key: value for key, value in catalog.items() if key in grants}


def set_grants(state, uid, owner, body):
    if not is_owner(state, uid, owner):
        raise Forbidden()
    target, threads = body.get('user_id'), body.get('threads')
    if target not in state['bindings'].values() or not isinstance(threads, list) or not all(t in state.get('catalog', {}) for t in threads):
        raise domain.Rejected('Invalid grant')
    state.setdefault('thread_grants', {})[str(target)] = list(dict.fromkeys(threads))
    for item in state['items'].values():
        if item.get('channel') == 'web' and item['sender'] == target and item['thread'] not in threads and item['status'] in ('approved', 'awaiting_approval'):
            item['status'] = 'target_unavailable'
    return {'ok': True}


def public_item(item):
    keys = ('id', 'sender', 'thread', 'text', 'created', 'expires', 'status', 'snapshot', 'events', 'result_status', 'attachments')
    return {k: item[k] for k in keys if k in item}


def view(state, uid, owner, now):
    domain.cleanup(state, now)
    admin = is_owner(state, uid, owner)
    catalog = permitted_threads(state, uid, owner)
    result = {'user': {'id': uid, 'role': 'owner' if admin else 'member'},
              'threads': list(catalog.values()), 'catalog_updated': state.get('catalog_updated'),
              'collector_seen': state.get('collector_seen'), 'messages': [public_item(item) for item in state['items'].values()
                if item.get('channel') == 'web' and (admin or item['thread'] in catalog)]}
    result['weekly_quota'] = state.get('weekly_quota')
    if admin:
        result['members'] = [{'id': ident, 'username': name, 'threads': state.get('thread_grants', {}).get(str(ident), [])}
                             for name, ident in state['bindings'].items() if name != owner]
    return result


def submit(state, uid, owner, body, now):
    domain.cleanup(state, now)
    thread, text, nonce = body.get('thread'), body.get('text'), body.get('request_id')
    if thread not in permitted_threads(state, uid, owner) or state['catalog'][thread].get('read_only'):
        raise Forbidden()
    attachment_ids = body.get('attachments', [])
    if (not isinstance(attachment_ids,list) or len(attachment_ids)>4
            or not all(isinstance(ident,str) for ident in attachment_ids) or len(set(attachment_ids))!=len(attachment_ids)):
        raise domain.Rejected('Invalid attachments')
    if not isinstance(text, str) or not (text.strip() or attachment_ids) or len(text) > MAX_TEXT or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', str(nonce)):
        raise domain.Rejected('Invalid message')
    attachments=[]
    for ident in attachment_ids:
        upload=state.get('uploads',{}).get(ident)
        if (not upload or upload['owner']!=uid or upload['thread']!=thread
                or upload['status']!='ready' or upload['expires']<=now):
            raise domain.Rejected('Attachment unavailable')
        attachments.append({k:upload[k] for k in ('id','name','size','sha256')})
    fingerprint = hashlib.sha256(json.dumps([thread, text, attachments], ensure_ascii=False).encode()).hexdigest()
    source = f'web:{uid}:{nonce}'
    for item in state['items'].values():
        if item['source'] == source:
            if item['snapshot'] != fingerprint:
                raise domain.Rejected('Idempotency conflict')
            return public_item(item)
    if len(state['items']) >= domain.MAX_ITEMS:
        raise domain.Rejected('Mailbox full')
    if any('used_by' in state['uploads'][a['id']] for a in attachments):
        raise domain.Rejected('Attachment already submitted')
    # Telegram update IDs are nonnegative; local Web IDs use another space.
    ident = state.get('web_sequence', 0) - 1
    state['web_sequence'] = ident
    item = dict(id=ident, source=source, channel='web', sender=uid, message=0,
        thread=thread, text=text, snapshot=fingerprint, created=now, expires=now + domain.APPROVAL_TTL,
        status='awaiting_approval', nonce=secrets.token_urlsafe(18), card='disabled', reply='none', events=[], attachments=attachments)
    if is_owner(state, uid, owner):
        item.update(status='approved', approved_by=uid, decision_at=now)
    state['items'][str(ident)] = item
    for attachment in attachments:
        state['uploads'][attachment['id']]['used_by']=ident
    return public_item(item)


def decision(state, uid, owner, body, now):
    domain.cleanup(state, now)
    if not is_owner(state, uid, owner):
        raise Forbidden()
    item = state['items'].get(str(body.get('id')))
    action = body.get('decision')
    if not item or item.get('channel') != 'web' or action not in ('approved', 'rejected') or body.get('snapshot') != item['snapshot']:
        raise domain.Rejected('Invalid decision')
    if item['status'] == action:
        return public_item(item)
    if (item['status'] != 'awaiting_approval' or item['thread'] not in permitted_threads(state, item['sender'], owner) or state['catalog'][item['thread']].get('read_only')):
        raise domain.Rejected('Decision no longer valid')
    item.update(status=action, approved_by=uid, decision_at=now)
    return public_item(item)


def collect(state, now, owner):
    domain.cleanup(state, now)
    state['collector_seen'] = now
    for item in state['items'].values():
        if (item.get('channel') == 'web' and item['status'] == 'approved' and item.get('lease_until', 0) <= now
                and item['thread'] in permitted_threads(state, item['sender'], owner) and not state['catalog'][item['thread']].get('read_only')):
            item['lease'] = secrets.token_urlsafe(24)
            item['lease_until'] = now + 120
            return {**{k: item[k] for k in ('id', 'text', 'thread', 'snapshot', 'lease', 'created')},
                    'attachments':item.get('attachments',[])}
    return None



def dispatch_allowed(state, body, now, owner):
    """Recheck a downloaded request before the laptop starts its Codex turn."""
    item = state['items'].get(str(body.get('id')))
    if (not item or item.get('channel') != 'web' or item['status'] != 'delivered'
            or item['expires'] <= now or item['thread'] != body.get('thread')
            or item['snapshot'] != body.get('snapshot')):
        return {'allowed': False}
    try:
        permitted = permitted_threads(state, item['sender'], owner)
    except Forbidden:
        return {'allowed': False}
    target = permitted.get(item['thread'])
    return {'allowed': bool(target and not target.get('read_only'))}


def publish(state, body, now):
    """Local trusted collector publishes only the response to this bridge request."""
    item = state['items'].get(str(body.get('id')))
    if not item or item.get('channel') != 'web' or item['status'] != 'delivered' or item['thread'] != body.get('thread'):
        raise domain.Rejected('Invalid response target')
    events, revision, status = body.get('events'), body.get('revision'), body.get('status')
    if (not isinstance(events, list) or len(events) > 100 or type(revision) is not int or revision < 1
            or status not in ('running', 'completed', 'failed', 'needs_input')):
        raise domain.Rejected('Invalid response')
    # Explicit public presentation types. Never publish hidden reasoning, raw
    # tool output, account metadata, environment variables or session history.
    clean = []
    for event in events:
        if not isinstance(event, dict) or event.get('type') not in ('agent_message', 'file_change', 'plan_update', 'error'):
            raise domain.Rejected('Unsupported public event')
        clean.append(public_event(event, len(clean)))
    encoded = json.dumps(clean, ensure_ascii=False)
    if len(encoded.encode()) > 100000:
        raise domain.Rejected('Response too large')
    digest = hashlib.sha256(json.dumps([clean, status], sort_keys=True).encode()).hexdigest()
    previous = item.get('result_revision', 0)
    if revision < previous or revision == previous and digest != item.get('result_digest'):
        raise domain.Rejected('Response revision conflict')
    if revision > previous:
        if item.get('result_status') in ('completed', 'failed'):
            raise domain.Rejected('Response already finished')
        item.update(events=clean, result_revision=revision, result_digest=digest,
                    result_status=status, result_updated=now)
    return {'ok': True, 'revision': revision}


def public_event(event, index):
    kind = event['type']
    result = {'type': kind, 'id': str(index)}

    def text(key, limit=60000, optional=False):
        value = event.get(key)
        if optional and value is None:
            return
        if not isinstance(value, str) or len(value) > limit:
            raise domain.Rejected('Invalid event field')
        result[key] = value

    if kind == 'agent_message':
        text('text')
    elif kind == 'error':
        text('message', 4000)
        result['severity'] = 'warning' if event.get('severity') == 'warning' else 'error'
    elif kind == 'file_change':
        if event.get('change') not in ('create', 'edit', 'delete', 'rename'):
            raise domain.Rejected('Invalid file change')
        result['change'] = event['change']
        text('path', 500)
        text('oldPath', 500, True)
        for key in ('path', 'oldPath'):
            path = result.get(key, '')
            if path.startswith(('/', '\\', '~')) or ':' in path or '..' in path.replace('\\', '/').split('/'):
                raise domain.Rejected('Only relative paths may be published')
        text('patch', 60000, True)
    elif kind == 'plan_update':
        text('status', 100, True)
        plan = event.get('plan', [])
        if not isinstance(plan, list) or len(plan) > 40:
            raise domain.Rejected('Invalid plan')
        result['plan'] = []
        for step in plan:
            if (not isinstance(step, dict) or not isinstance(step.get('step'), str)
                    or len(step['step']) > 1000 or step.get('status') not in ('pending', 'in_progress', 'completed', 'failed')):
                raise domain.Rejected('Invalid plan step')
            result['plan'].append({'step': step['step'], 'status': step['status']})
    return result
