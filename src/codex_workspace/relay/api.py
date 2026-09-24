"""VM HTTP adapters with injected transactional storage.

No YDB, Telegram Bot API, webhook worker or Cloud Functions entrypoints.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from codex_workspace.domain import domain, workspace


def response(code, value):
    return {'statusCode': code, 'headers': {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
            'body': json.dumps(value), 'isBase64Encoded': False}


def authorized(event):
    headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
    supplied = headers.get('authorization', '')
    if not supplied.startswith('Bearer '):
        return False
    return secrets.compare_digest(hashlib.sha256(supplied[7:].encode()).hexdigest(), os.environ['CLIENT_KEY_HASH'])


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



def website(event, context):
    """Serve only build-manifest entries, never arbitrary filesystem paths."""
    from pathlib import Path
    root = Path(os.environ.get('WORKSPACE_STATIC', '/opt/codex-workspace/current/static'))
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
                'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}}
