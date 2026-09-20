"""Telegram OIDC and Login Widget verification. OIDC keys use a fixed HTTPS URL."""
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.request
from .workspace import Unauthorized

ISSUER = 'https://oauth.telegram.org'
JWKS_URL = ISSUER + '/.well-known/jwks.json'
_KEYS = None
_KEYS_UNTIL = 0
CACHE_TTL = 24 * 3600


def cache_keys(state, body, now):
    """Trusted collector/deployer only; browsers cannot update trust anchors."""
    keys, fetched = body.get('keys'), body.get('fetched_at')
    if type(fetched) is not int or not now - 300 <= fetched <= now + 30:
        raise ValueError('Invalid key fetch time')
    if not isinstance(keys, list) or not 1 <= len(keys) <= 20:
        raise ValueError('Invalid key set')
    clean = []
    for key in keys:
        if not isinstance(key, dict) or any(k in key for k in ('d','p','q','dp','dq','qi')):
            raise ValueError('Invalid public key')
        # Only keys usable by our deliberately RS256-only client.
        if key.get('kty') != 'RSA' or key.get('alg','RS256') != 'RS256':
            continue
        if not all(isinstance(key.get(k),str) and 0 < len(key[k]) <= 2048 for k in ('kid','n','e')):
            raise ValueError('Invalid RSA key')
        clean.append({k:key[k] for k in ('kty','kid','n','e','alg','use') if k in key})
    if not clean:
        raise ValueError('No supported public keys')
    state['login_jwks'] = {'keys':clean, 'fetched_at':fetched}
    return {'ok':True,'expires_at':fetched+CACHE_TTL}


def cached_keys(state, now):
    bundle = state.get('login_jwks', {})
    if now - CACHE_TTL < bundle.get('fetched_at', 0) <= now + 30:
        return bundle.get('keys')
    return None


def new_challenge(secret, now):
    nonce = secrets.token_urlsafe(32)
    expires = now + 300
    data = f'{nonce}.{expires}'
    signature = hmac.new(secret.encode(), ('login:' + data).encode(), hashlib.sha256).hexdigest()
    return {'nonce': nonce, 'challenge': data + '.' + signature}


def verify_challenge(challenge, secret, now):
    try:
        nonce, expiry, signature = challenge.split('.')
        if len(challenge) > 250 or not now < int(expiry) <= now + 300:
            raise Unauthorized()
        actual = hmac.new(secret.encode(), f'login:{nonce}.{expiry}'.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, actual):
            raise Unauthorized()
        return nonce
    except (ValueError, TypeError, AttributeError):
        raise Unauthorized() from None


def public_keys(refresh=False):
    global _KEYS, _KEYS_UNTIL
    if _KEYS is None or _KEYS_UNTIL < time.time() or refresh:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        request = urllib.request.Request(JWKS_URL, headers={'Accept': 'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
            data = response.read(65537)
        if len(data) > 65536:
            raise RuntimeError('Invalid JWKS')
        result = json.loads(data)
        if not isinstance(result.get('keys'), list) or len(result['keys']) > 20:
            raise RuntimeError('Invalid JWKS')
        _KEYS, _KEYS_UNTIL = result['keys'], time.time() + 3600
    return _KEYS


def verify_id_token(token, client_id, nonce, now, keys=None):
    import jwt
    try:
        if not isinstance(token, str) or len(token) > 20000:
            raise Unauthorized()
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str):
            raise Unauthorized()
        candidates = public_keys() if keys is None else keys
        key = next((k for k in candidates if k.get('kid') == header['kid']), None)
        if key is None and keys is None:
            key = next((k for k in public_keys(refresh=True) if k.get('kid') == header['kid']), None)
        if not key or key.get('kty') != 'RSA' or key.get('use', 'sig') != 'sig' or key.get('alg', 'RS256') != 'RS256':
            raise Unauthorized()
        claims = jwt.decode(token, jwt.PyJWK.from_dict(key, algorithm='RS256').key,
            algorithms=['RS256'], audience=str(client_id), issuer=ISSUER,
            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'nonce', 'id'],
                     'verify_exp': False, 'verify_iat': False})
        if (type(claims['exp']) is not int or type(claims['iat']) is not int
                or claims['exp'] <= now or not now - 300 <= claims['iat'] <= now + 30
                or not secrets.compare_digest(str(claims['nonce']), nonce)
                or type(claims['id']) is not int or claims['id'] <= 0):
            raise Unauthorized()
        return {'id': claims['id'], 'username': str(claims.get('preferred_username', '')).lower()}
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise Unauthorized() from None


def consume_challenge(state, nonce, now):
    used = {k: v for k, v in state.get('login_nonces', {}).items() if v > now - 300}
    if nonce in used or len(used) >= 1000:
        raise Unauthorized()
    used[nonce] = now
    state['login_nonces'] = used


def verify_widget(data, secret, now):
    """Verify Telegram Login Widget's documented SHA256(bot token) HMAC.

    This is not Mini App initData. Every supplied profile field is signed;
    unknown, nested or ambiguous values are rejected instead of discarded.
    """
    allowed = {'id','first_name','last_name','username','photo_url','auth_date','hash'}
    if (not isinstance(data,dict) or set(data)-allowed
            or not {'id','auth_date','hash'}.issubset(data)):
        raise Unauthorized()
    signature=data['hash']
    if not isinstance(signature,str) or not re.fullmatch('[0-9a-f]{64}',signature):
        raise Unauthorized()
    for key,value in data.items():
        if key in ('id','auth_date'):
            if type(value) not in (str,int) or not re.fullmatch('[0-9]{1,20}',str(value)):
                raise Unauthorized()
        elif not isinstance(value,str) or len(value)>2048 or '\n' in value or '\r' in value:
            raise Unauthorized()
    uid,issued=int(data['id']),int(data['auth_date'])
    if uid<=0 or not now-300<=issued<=now+30:
        raise Unauthorized()
    username=data.get('username','')
    if username and not re.fullmatch('[A-Za-z0-9_]{1,32}',username):
        raise Unauthorized()
    canonical='\n'.join(f'{key}={data[key]}' for key in sorted(data) if key!='hash')
    expected=hmac.new(hashlib.sha256(secret.encode()).digest(),canonical.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,signature):
        raise Unauthorized()
    return {'id':uid,'username':username.lower()}


def consume_widget(state, signature, now):
    # The widget format has no signed nonce. Independently consume the signed
    # proof as well as our challenge, so a new challenge cannot replay it.
    used={k:v for k,v in state.get('login_widget_proofs',{}).items() if v>now-360}
    digest=hashlib.sha256(signature.encode()).hexdigest()
    if digest in used or len(used)>=1000:
        raise Unauthorized()
    used[digest]=now
    state['login_widget_proofs']=used
