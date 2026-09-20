"""Yandex Cloud entrypoints. Request bodies and secrets must never be logged."""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.request
from . import domain

_POOL = None


def pool():
    global _POOL
    if _POOL is None:
        import ydb
        import ydb.iam
        driver = ydb.Driver(endpoint=os.environ['YDB_ENDPOINT'], database=os.environ['YDB_DATABASE'],
                            credentials=ydb.iam.MetadataUrlCredentials())
        driver.wait(timeout=10, fail_fast=True)
        _POOL = ydb.SessionPool(driver, size=4)
    return _POOL


def mutate(operation):
    """One bounded mailbox row, serialized by YDB; no external I/O in retries."""
    import ydb
    def transaction(session):
        tx = session.transaction(ydb.SerializableReadWrite())
        result = tx.execute('SELECT value FROM mailbox WHERE id = 1;')
        state = json.loads(result[0].rows[0].value) if result[0].rows else domain.initial()
        output = operation(state)
        value = json.dumps(state, ensure_ascii=False)
        if len(value.encode()) > 3000000:
            raise domain.Rejected('Mailbox capacity')
        query = session.prepare('DECLARE $value AS Utf8; UPSERT INTO mailbox (id,value) VALUES (1,$value);')
        tx.execute(query, {'$value': value}, commit_tx=True)
        return output
    return pool().retry_operation_sync(transaction)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def telegram(method, params):
    # Fail closed on any ambiguous result. Caller records uncertain; no retry.
    url = 'https://api.telegram.org/bot' + os.environ['TELEGRAM_BOT_TOKEN'] + '/' + method
    headers = {'Content-Type': 'application/json'}
    data = json.dumps(params).encode()
    if method == 'sendMessage' and len(params.get('text', '')) > 4096:
        method = 'sendDocument'
        url = url.rsplit('/', 1)[0] + '/' + method
        boundary = secrets.token_hex(24)
        fields = {k: v for k, v in params.items() if k != 'text'}
        fields['caption'] = 'Полный текст запроса в UTF-8 файле. Кнопка одобряет именно этот текст.'
        parts = []
        for key, value in fields.items():
            if isinstance(value, dict):
                value = json.dumps(value)
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="request.txt"\r\n'
                      'Content-Type: text/plain; charset=utf-8\r\n\r\n').encode() + params['text'].encode() + b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        data = b''.join(parts)
        headers = {'Content-Type': 'multipart/form-data; boundary=' + boundary}
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
        result = json.load(response)
    if not result.get('ok'):
        raise RuntimeError('Telegram rejected request')
    return result['result']


def response(code, value):
    return {'statusCode': code, 'headers': {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
            'body': json.dumps(value), 'isBase64Encoded': False}


def authorized(event):
    headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
    supplied = headers.get('authorization', '')
    if not supplied.startswith('Bearer '):
        return False
    return secrets.compare_digest(hashlib.sha256(supplied[7:].encode()).hexdigest(), os.environ['CLIENT_KEY_HASH'])


def authorizer(event, context):
    return {'isAuthorized': authorized(event), 'context': {'mailbox': 'primary'}}


def api(event, context):
    try:
        path = event.get('path', '')
        method = event.get('httpMethod')
        if path == '/health' and method == 'GET':
            return response(200, {'status': 'ok', 'mode': 'text-owner-approval'})
        if not authorized(event):
            return response(401, {'error': 'unauthorized'})
        body = decode(event)
        now = int(time.time())
        if method != 'POST':
            return response(405, {'error': 'method'})
        if path == '/v1/inbox/claim':
            return response(200, {'message': mutate(lambda s: domain.claim(s, now))})
        if path == '/v1/inbox/ack':
            mutate(lambda s: domain.receipt(s, body, now))
            return response(200, {'status': 'delivered'})
        if path == '/v1/replies':
            return response(200, mutate(lambda s: domain.acknowledge(s, body, now)))
        return response(404, {'error': 'not_found'})
    except domain.Rejected:
        return response(409, {'error': 'conflict'})
    except (ValueError, TypeError, KeyError):
        return response(400, {'error': 'invalid_request'})
    except Exception:
        return response(503, {'error': 'temporarily_unavailable'})


def decode(event):
    body = event.get('body') or '{}'
    if len(body) > 100000:
        raise ValueError('Too large')
    if event.get('isBase64Encoded'):
        body = base64.b64decode(body, validate=True)
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError('Not an object')
    return result


def webhook(event, context):
    headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
    if not secrets.compare_digest(headers.get('x-telegram-bot-api-secret-token', ''), os.environ['WEBHOOK_SECRET']):
        return response(403, {'error': 'forbidden'})
    try:
        update = decode(event)
        mutate(lambda s: domain.ingest(s, update, int(time.time()), os.environ['OWNER_USERNAME'],
                                       os.environ['ALLOWED_USERNAMES'].split('|'), os.environ['THREAD_ID']))
        # No background jobs after return: timer drains the persisted outbox.
        return response(200, {'ok': True})
    except (ValueError, TypeError, KeyError):
        return response(400, {'error': 'invalid_update'})
    except Exception:
        return response(503, {'error': 'temporarily_unavailable'})


def worker(event, context):
    try:
        for _ in range(4):
            job = mutate(lambda s: domain.take_send(s, int(time.time()), os.environ['OWNER_USERNAME']))
            if not job:
                break
            message_id = None
            try:
                message_id = telegram('sendMessage', job['params'])['message_id']
            except Exception:
                pass
            mutate(lambda s: domain.finish_send(s, job, message_id))
        return {'status': 'ok'}
    except Exception:
        return {'status': 'retry_next_tick'}


def admin(event, context):
    """Private IAM-only deployment entrypoint; never exposed by Gateway."""
    try:
        action = event.get('action')
        if action == 'network':
            import socket
            checks = {}
            for host in ('api.telegram.org', 'api.github.com'):
                try:
                    addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
                    with socket.create_connection((host, 443), timeout=4):
                        pass
                    checks[host] = {'tcp': 'ok', 'addresses': addresses}
                except Exception as exc:
                    checks[host] = {'tcp': type(exc).__name__}
            return {'checks': checks}
        if action == 'initialize':
            def create(session):
                session.execute_scheme('CREATE TABLE IF NOT EXISTS mailbox (id Uint64, value Utf8, PRIMARY KEY (id));')
            pool().retry_operation_sync(create)
            bot = telegram('getMe', {})
            return {'ok': True, 'bot': bot['username']}
        if action == 'activate':
            url = event['url']
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme != 'https' or not parsed.hostname.endswith('.apigw.yandexcloud.net') or parsed.path != '/telegram/webhook':
                raise ValueError('Invalid gateway')
            return {'ok': telegram('setWebhook', {'url': url, 'secret_token': os.environ['WEBHOOK_SECRET'],
                        'allowed_updates': ['message', 'edited_message', 'callback_query'],
                        'max_connections': 2, 'drop_pending_updates': False})}
        if action == 'status':
            def status(s):
                domain.cleanup(s, int(time.time()))
                counts = {}
                for item in s['items'].values():
                    key = item['status'] + '/' + item['card'] + '/' + item['reply']
                    counts[key] = counts.get(key, 0) + 1
                return {'bound_users': sorted(s['bindings']), 'counts': counts}
            info = telegram('getWebhookInfo', {})
            return {'state': mutate(status), 'pending_updates': info.get('pending_update_count'),
                    'webhook_error': bool(info.get('last_error_date'))}
        return {'ok': False}
    except Exception as exc:
        return {'ok': False, 'error': 'admin_operation_failed', 'category': type(exc).__name__, 'reason': type(getattr(exc, 'reason', None)).__name__}
