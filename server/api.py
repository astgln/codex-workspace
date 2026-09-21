"""VM HTTP adapters with injected transactional storage.

No YDB, Telegram Bot API, webhook worker or Cloud Functions entrypoints.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from cloud import domain, workspace


def response(code, value):
    return {'statusCode': code, 'headers': {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
            'body': json.dumps(value), 'isBase64Encoded': False}


def authorized(event):
    headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
    supplied = headers.get('authorization', '')
    if not supplied.startswith('Bearer '):
        return False
    return secrets.compare_digest(hashlib.sha256(supplied[7:].encode()).hexdigest(), os.environ['CLIENT_KEY_HASH'])


def api(event, context=None, *, mutate):
    try:
        path = event.get('path', '')
        method = event.get('httpMethod')
        if path == '/health' and method == 'GET':
            return response(200, {'status': 'ok', 'mode': 'single-user'})
        if not authorized(event):
            return response(401, {'error': 'unauthorized'})
        body = decode(event)
        now = int(time.time())
        if method != 'POST':
            return response(405, {'error': 'method'})
        if path == '/v2/worker/status':
            from cloud.worker_status import save
            return response(200, mutate(lambda s: save(s, body, now)))
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


def web_api(event, context=None, *, mutate):
    """Website API authenticated by verified Telegram Login, never Mini App data."""
    from cloud import workspace, login
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
                return workspace.bind_user(state, user, owner)
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
    root = Path(__file__).resolve().parent.parent / 'cloud' / 'static'
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
