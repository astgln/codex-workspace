"""Request submission, leasing and pre-dispatch validation."""
import hashlib
import json
import re
import secrets
from . import domain
from .redaction import public_value
from .access import Forbidden, can_submit

MAX_TEXT = 16000


def public_item(item):
    keys = ('id', 'sender', 'thread', 'text', 'created', 'expires', 'status', 'snapshot', 'events', 'result_status', 'attachments')
    return {k: public_value(item[k]) if k == 'events' else item[k] for k in keys if k in item}


def submit(state, uid, owner, body, now):
    domain.cleanup(state, now)
    thread, text, nonce = body.get('thread'), body.get('text'), body.get('request_id')
    if not can_submit(state, uid, owner, thread):
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
    # Preserve stable negative IDs across database upgrades.
    ident = state.get('web_sequence', 0) - 1
    state['web_sequence'] = ident
    item = dict(id=ident, source=source, channel='web', sender=uid, message=0,
        thread=thread, text=text, snapshot=fingerprint, created=now, expires=now + domain.REQUEST_TTL,
        status='queued', events=[], attachments=attachments)
    state['items'][str(ident)] = item
    for attachment in attachments:
        state['uploads'][attachment['id']]['used_by']=ident
    return public_item(item)


def collect(state, now, owner):
    domain.cleanup(state, now)
    state['collector_seen'] = now
    for item in state['items'].values():
        if (item.get('channel') == 'web' and item['status'] == 'queued' and item.get('lease_until', 0) <= now
                and can_submit(state, item['sender'], owner, item['thread'])):
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
        allowed = can_submit(state, item['sender'], owner, item['thread'])
    except Forbidden:
        return {'allowed': False}
    return {'allowed': allowed}
