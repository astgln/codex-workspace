"""Revisioned response publication with explicit public event types."""
import hashlib
import json
import re
from . import domain
from .redaction import public_text, public_value


def publish(state, body, now):
    """Local trusted collector publishes only the response to this bridge request."""
    item = state['items'].get(str(body.get('id')))
    if not item or item.get('channel') != 'web' or item['status'] != 'delivered' or item['thread'] != body.get('thread'):
        raise domain.Rejected('Invalid response target')
    turn = body.get('turn_id')
    if turn is not None and (not isinstance(turn,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',turn)):
        raise domain.Rejected('Invalid response turn')
    if item.get('result_turn_id') and turn != item['result_turn_id']:
        raise domain.Rejected('Response moved to another turn')
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
    if 'events' in item and 'result_status' in item:
        filtered = public_value(item['events'])
        if filtered != item['events']:
            item['events'] = filtered
            item['result_digest'] = hashlib.sha256(json.dumps([filtered, item['result_status']], sort_keys=True).encode()).hexdigest()
    previous = item.get('result_revision', 0)
    if revision < previous or revision == previous and digest != item.get('result_digest'):
        raise domain.Rejected('Response revision conflict')
    if revision > previous:
        if item.get('result_status') in ('completed', 'failed'):
            raise domain.Rejected('Response already finished')
        item.update(events=clean, result_revision=revision, result_digest=digest,
                    result_status=status, result_updated=now)
    if turn is not None:
        item['result_turn_id'] = turn
    state['collector_seen'] = now
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
        result[key] = public_text(value)

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
            result['plan'].append({'step': public_text(step['step']), 'status': step['status']})
    return result
