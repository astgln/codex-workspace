"""Verified identity binding and internal short-lived signed sessions."""
import base64
import hashlib
import hmac
import json
import secrets
from .access import Forbidden

SESSION_TTL = 8 * 3600


class Unauthorized(Exception):
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
