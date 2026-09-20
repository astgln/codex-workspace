"""Yandex Cloud entrypoints. Request bodies and secrets must never be logged."""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.request
from . import domain, workspace

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
        if path == '/v2/login-keys':
            from . import login
            return response(200, mutate(lambda s: login.cache_keys(s, body, now)))
        if path == '/v2/catalog':
            return response(200, mutate(lambda s: workspace.sync_catalog(s, body, os.environ['PROJECT_ID'], now)))
        if path == '/v2/inbox/claim':
            return response(200, {'message': mutate(lambda s: workspace.collect(s, now, os.environ['OWNER_USERNAME']))})
        if path == '/v2/inbox/validate':
            return response(200, mutate(lambda s: workspace.dispatch_allowed(s, body, now, os.environ['OWNER_USERNAME'])))
        if path == '/v2/inbox/ack':
            mutate(lambda s: domain.receipt(s, body, now))
            return response(200, {'status': 'delivered'})
        if path == '/v2/responses':
            return response(200, mutate(lambda s: workspace.publish(s, body, now)))
        if path == '/v1/inbox/claim':
            return response(200, {'message': mutate(lambda s: domain.claim(s, now, channel='telegram'))})
        if path == '/v1/inbox/ack':
            mutate(lambda s: domain.receipt(s, body, now))
            return response(200, {'status': 'delivered'})
        if path == '/v1/replies':
            return response(200, mutate(lambda s: domain.acknowledge(s, body, now)))
        return response(404, {'error': 'not_found'})
    except workspace.Forbidden:
        return response(403, {'error': 'access_denied'})
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
        if action == 'export_migration':
            # Private IAM-only entrypoint. Never expose this through the web API.
            return {'ok':True,'state':mutate(lambda state:state)}
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
        if action in ('initialize', 'initialize_web'):
            def create(session):
                session.execute_scheme('CREATE TABLE IF NOT EXISTS mailbox (id Uint64, value Utf8, PRIMARY KEY (id));')
            pool().retry_operation_sync(create)
            if action == 'initialize_web':
                return {'ok': True}
            bot = telegram('getMe', {})
            return {'ok': True, 'bot': bot['username']}
        if action == 'login_keys':
            from . import login
            return mutate(lambda s: login.cache_keys(s, event, int(time.time())))
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



def web_api(event, context):
    """Website API authenticated by verified Telegram Login, never Mini App data."""
    from . import workspace, login
    try:
        path = event.get('path', '')
        now = int(time.time())
        secret = os.environ['TELEGRAM_BOT_TOKEN']
        client_id = os.environ.get('LOGIN_CLIENT_ID') or secret.split(':', 1)[0]
        owner = os.environ['OWNER_USERNAME']
        if path == '/web/login/config' and event.get('httpMethod') == 'GET':
            return response(200, {'client_id': client_id, **login.new_challenge(secret, now)})
        if event.get('httpMethod') != 'POST':
            return response(405, {'error': 'method'})
        body = decode(event)
        if path == '/web/login/session':
            nonce = login.verify_challenge(body.get('challenge'), secret, now)
            if ('widget_data' in body) == ('id_token' in body):
                raise workspace.Unauthorized()
            widget = body.get('widget_data') if 'widget_data' in body else None
            if 'widget_data' in body:
                user = login.verify_widget(widget, secret, now)
            else:
                keys = mutate(lambda state: login.cached_keys(state, now))
                user = login.verify_id_token(body.get('id_token'), client_id, nonce, now, keys=keys)
            def authenticate(state):
                login.consume_challenge(state, nonce, now)
                if widget is not None:
                    login.consume_widget(state, widget['hash'], now)
                return workspace.bind_user(state, user, os.environ['ALLOWED_USERNAMES'].split('|'))
            uid = mutate(authenticate)
            return response(200, {'token': workspace.issue_session(uid, secret, now), 'expires_in': workspace.SESSION_TTL})
        headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
        authorization = headers.get('authorization', '')
        if not authorization.startswith('Workspace '):
            raise workspace.Unauthorized()
        uid = workspace.verify_session(authorization[10:], secret, now)
        routes = {
            '/web/state': lambda s: workspace.view(s, uid, owner, now),
            '/web/messages': lambda s: workspace.submit(s, uid, owner, body, now),
            '/web/decisions': lambda s: workspace.decision(s, uid, owner, body, now),
            '/web/member-policy': lambda s: workspace.set_member_policy(s, uid, owner, body),
            '/web/grants': lambda s: workspace.set_grants(s, uid, owner, body),
        }
        if path not in routes:
            return response(404, {'error': 'not_found'})
        return response(200, mutate(routes[path]))
    except workspace.Unauthorized:
        return response(401, {'error': 'telegram_login_required'})
    except workspace.Forbidden:
        return response(403, {'error': 'access_denied'})
    except domain.Rejected:
        return response(409, {'error': 'conflict'})
    except (ValueError, TypeError, KeyError):
        return response(400, {'error': 'invalid_request'})
    except Exception:
        return response(503, {'error': 'temporarily_unavailable'})


def website(event, context):
    """Serve only build-manifest entries, never arbitrary filesystem paths."""
    from pathlib import Path
    root = Path(__file__).resolve().parent / 'static'
    manifest = json.loads((root / 'files.json').read_text())
    path = event.get('path', '/')
    if event.get('httpMethod') != 'GET' or path not in manifest:
        return response(404, {'error': 'not_found'})
    entry = manifest[path]
    data = (root / entry['file']).read_bytes()
    return {'statusCode': 200, 'isBase64Encoded': True,
            'body': base64.b64encode(data).decode(), 'headers': {
                'Content-Type': entry['type'],
                'Cache-Control': 'no-store' if path in ('/', '/sw.js', '/manifest.webmanifest') else 'public, max-age=31536000, immutable',
                'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                'Cross-Origin-Opener-Policy': 'same-origin-allow-popups',
                'Content-Security-Policy': "default-src 'self'; script-src 'self' https://oauth.telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self' https://oauth.telegram.org; frame-src https://oauth.telegram.org; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self' https://oauth.telegram.org"}}
