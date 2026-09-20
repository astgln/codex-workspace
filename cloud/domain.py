"""Pure text-only approval state machine. Never performs I/O in transactions."""
import hashlib
import secrets

APPROVAL_TTL = 86400
RETENTION = 7 * 86400
MAX_ITEMS = 200
ACK = 'Сообщение получено в задаче Codex. Тест доставки и обратного ответа прошёл. Пока это проверка связи; разбор логов ещё не подключён.'


class Rejected(Exception):
    pass


def initial():
    return {'bindings': {}, 'items': {}, 'seen': {}}


def cleanup(state, now):
    state['seen'] = {k: v for k, v in state['seen'].items() if v > now - RETENTION}
    state['items'] = {k: v for k, v in state['items'].items() if v['created'] > now - RETENTION}
    for item in state['items'].values():
        if item['status'] in ('awaiting_approval', 'approved') and item['expires'] <= now:
            item['status'] = 'expired'
        for operation in ('card', 'reply'):
            if item.get(operation) == 'sending' and item.get(operation + '_started', 0) < now - 120:
                item[operation] = 'uncertain'


def private(message):
    sender = message.get('from', {})
    chat = message.get('chat', {})
    return (type(sender.get('id')) is int and sender['id'] > 0
            and not sender.get('is_bot') and chat.get('type') == 'private'
            and chat.get('id') == sender['id'])


def ingest(state, update, now, owner, allowed, thread):
    cleanup(state, now)
    uid = update.get('update_id')
    if type(uid) is not int:
        raise Rejected('Invalid update')
    key = str(uid)
    if key in state['seen'] or key in state['items']:
        return
    message = update.get('message') or update.get('edited_message')
    if message and private(message):
        sender = message['from']
        username = sender.get('username', '').lower()
        # Explicitly configured names are bootstrap-only. Bind once to immutable IDs.
        if username in allowed and username not in state['bindings']:
            state['bindings'][username] = sender['id']
        if sender['id'] in state['bindings'].values():
            source = f"{sender['id']}:{message['message_id']}"
            for old in state['items'].values():
                if old['source'] == source and old['status'] in ('awaiting_approval', 'approved'):
                    old['status'] = 'superseded'
            text = message.get('text')
            # Attachments are not accepted or represented as approved placeholders.
            if isinstance(text, str) and 0 < len(text) <= 4096:
                if len(state['items']) >= MAX_ITEMS:
                    raise Rejected('Mailbox full')
                nonce = secrets.token_urlsafe(18)
                snapshot = hashlib.sha256((thread + '\0' + source + '\0' + text).encode()).hexdigest()
                state['items'][key] = dict(id=uid, source=source, sender=sender['id'],
                    message=message['message_id'], text=text, thread=thread,
                    snapshot=snapshot, created=now, expires=now + APPROVAL_TTL,
                    status='awaiting_approval', nonce=nonce, card='ready', reply='none')
    callback = update.get('callback_query')
    if callback:
        owner_id = state['bindings'].get(owner)
        sender = callback.get('from', {})
        card = callback.get('message', {})
        if (owner_id and sender.get('id') == owner_id and not sender.get('is_bot')
                and card.get('chat', {}).get('type') == 'private'
                and card.get('chat', {}).get('id') == owner_id):
            data = callback.get('data', '')
            for item in state['items'].values():
                if (item['status'] == 'awaiting_approval' and item['expires'] > now
                        and item.get('card_id') == card.get('message_id')
                        and data in ('a:' + item['nonce'], 'r:' + item['nonce'])):
                    item['status'] = 'approved' if data.startswith('a:') else 'rejected'
                    item['approved_by'] = owner_id
                    item['decision_at'] = now
                    break
    # Bound replay markers independently from mailbox capacity. Ignored traffic
    # cannot grow this single-row MVP beyond its storage limit.
    state['seen'][key] = now
    if len(state['seen']) > 2000:
        oldest = sorted(state['seen'], key=lambda k: state['seen'][k])[:-2000]
        for old_key in oldest:
            del state['seen'][old_key]


def claim(state, now, channel=None):
    cleanup(state, now)
    for item in state['items'].values():
        if (item['status'] == 'approved' and item.get('lease_until', 0) <= now
                and (channel is None or item.get('channel', 'telegram') == channel)):
            item['lease'] = secrets.token_urlsafe(24)
            item['lease_until'] = now + 120
            return {k: item[k] for k in ('id', 'text', 'thread', 'snapshot', 'lease', 'created')}
    return None


def receipt(state, body, now):
    item = state['items'].get(str(body.get('id')))
    if not item or not secrets.compare_digest(item.get('lease', ''), str(body.get('lease', ''))) or not item.get('lease'):
        raise Rejected('Invalid receipt')
    if item['status'] == 'delivered':
        return
    if item['status'] != 'approved' or item['expires'] <= now or item.get('lease_until', 0) <= now:
        raise Rejected('Receipt expired')
    item['status'] = 'delivered'
    item['delivered_at'] = now


def acknowledge(state, body, now):
    item = state['items'].get(str(body.get('id')))
    if not item or item['status'] != 'delivered' or item['thread'] != body.get('thread'):
        raise Rejected('Not delivered to this thread')
    if item['reply'] == 'none':
        item['reply'] = 'ready'
    return {'status': item['reply'], 'message_id': item.get('reply_id')}


def take_send(state, now, owner):
    cleanup(state, now)
    owner_id = state['bindings'].get(owner)
    for item in state['items'].values():
        operation = None
        if owner_id and item['status'] == 'awaiting_approval' and item['card'] == 'ready':
            operation = 'card'
            # Full text fits separately; card uses sendMessage for <= 3500 chars.
            # Longer texts remain pending; worker sends a UTF-8 document with caption/buttons.
            params = dict(chat_id=owner_id, text=(
                f"Запрос от Telegram ID {item['sender']}\nЗадача: {item['thread']}\n"
                'Передать этот текст в Codex для анализа?\n\n' + item['text']),
                reply_markup={'inline_keyboard': [[
                    {'text': 'Передать в Codex', 'callback_data': 'a:' + item['nonce']},
                    {'text': 'Отклонить', 'callback_data': 'r:' + item['nonce']}]]})
        elif item['status'] == 'delivered' and item['reply'] == 'ready':
            operation = 'reply'
            params = dict(chat_id=item['sender'], text=ACK,
                          reply_parameters={'message_id': item['message']})
        if operation:
            item[operation] = 'sending'
            item[operation + '_started'] = now
            return dict(id=item['id'], operation=operation, params=params)
    return None


def finish_send(state, job, message_id):
    item = state['items'].get(str(job['id']))
    if item and item.get(job['operation']) == 'sending':
        operation = job['operation']
        item[operation] = 'sent' if message_id else 'uncertain'
        if message_id:
            item[operation + '_id'] = message_id
