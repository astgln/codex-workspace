#!/usr/bin/env python3
"""Explicit yc deployment. Secrets travel in HTTPS bodies, never argv or logs."""
import argparse
import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from bridge import read_token, NoRedirect

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.local'


def save(path, data):
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)
    temp.replace(path)


class Deploy:
    def __init__(self, args):
        self.args = args
        STATE.mkdir(mode=0o700, exist_ok=True)
        self.path = STATE / 'deployment.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        if self.state and self.state['folder'] != args.folder:
            raise RuntimeError('Deployment belongs to another folder')
        settings = {'thread': args.thread, 'owner': args.owner, 'allowed': sorted(args.allowed)}
        if args.owner not in args.allowed or not all(re.fullmatch(r'[a-z0-9_]{5,32}', x) for x in args.allowed):
            raise RuntimeError('Invalid owner or allowed usernames')
        if self.state.get('settings', settings) != settings:
            raise RuntimeError('Mailbox settings changed; explicit migration required')
        self.state['settings'] = settings
        if self.state.get('project', args.project) != args.project:
            raise RuntimeError('Project changed; explicit migration required')
        self.state['project'] = args.project
        self.state['folder'] = args.folder
        self.iam = None

    def checkpoint(self, key, value):
        self.state[key] = value
        save(self.path, self.state)
        return value

    def yc(self, *args):
        process = subprocess.run(['yc', *args, '--folder-id', self.args.folder, '--format', 'json'],
                                 capture_output=True, text=True)
        if process.returncode:
            # No user payload or secret is ever passed to yc. Still hide raw stderr.
            reason = 'permission denied' if 'PermissionDenied' in process.stderr else 'command failed'
            raise RuntimeError('yc ' + ' '.join(args[:3]) + ': ' + reason)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def resource(self, key, group, name, flags=()):
        if key in self.state:
            return self.state[key]
        existing = [r for r in self.yc(*group, 'list') if r.get('name') == name]
        if len(existing) > 1:
            raise RuntimeError('Ambiguous resource name ' + name)
        value = existing[0] if existing else self.yc(*group, 'create', '--name', name, *flags)
        print('Resource:', name, flush=True)
        return self.checkpoint(key, value['id'])

    def request(self, url, data=None):
        if self.iam is None:
            result = subprocess.run(['yc', 'iam', 'create-token'], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError('IAM authentication failed')
            self.iam = result.stdout.strip()
        request = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                 headers={'Authorization': 'Bearer ' + self.iam, 'Content-Type': 'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
            return json.load(response)

    def secrets(self):
        local = STATE / 'cloud-key.env'
        if not local.exists():
            fd = os.open(local, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write('BRIDGE_CLIENT_KEY=' + secrets.token_urlsafe(48) + '\n')
        key = local.read_text().strip().split('=', 1)[1]
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        if self.state.get('client_hash', key_hash) != key_hash:
            raise RuntimeError('Client key changed; explicit rotation required')
        self.checkpoint('client_hash', key_hash)
        if 'secret' not in self.state:
            # Refuse ambiguous recreate after a lost response.
            existing = self.yc('lockbox', 'secret', 'list')
            match = [x for x in existing if x.get('name') == 'telegram-codex']
            if match:
                self.checkpoint('secret', match[0]['id'])
                self.checkpoint('secret_version', match[0]['current_version']['id'])
                return
            values = {'TELEGRAM_BOT_TOKEN': read_token(STATE / '.env'),
                      'WEBHOOK_SECRET': secrets.token_urlsafe(48)}
            operation = self.request('https://lockbox.api.cloud.yandex.net/lockbox/v1/secrets', {
                'folderId': self.args.folder, 'name': 'telegram-codex', 'deletionProtection': True,
                'versionPayloadEntries': [{'key': k, 'textValue': v} for k, v in values.items()]})
            self.checkpoint('secret_operation', operation['id'])
            for _ in range(30):
                if operation.get('done'):
                    break
                time.sleep(1)
                operation = self.request('https://operation.api.cloud.yandex.net/operations/' + operation['id'])
            if not operation.get('done') or operation.get('error'):
                raise RuntimeError('Lockbox operation incomplete; inspect operation metadata')
            secret = operation['response']
            self.checkpoint('secret', secret['id'])
            self.checkpoint('secret_version', secret['currentVersion']['id'])
            print('Lockbox ready; secret values hidden', flush=True)

    def bind(self, group, resource, role, account):
        key = 'binding:' + resource + ':' + role + ':' + account
        if not self.state.get(key):
            self.yc(*group, 'add-access-binding', resource, '--role', role, '--service-account-id', account)
            self.checkpoint(key, True)

    def invoke(self, action):
        return self.request('https://functions.yandexcloud.net/' + self.state['fn_admin'] + '?integration=raw', action)

    def run(self):
        runtime = self.resource('runtime', ['iam', 'service-account'], 'telegram-codex-runtime')
        gateway_sa = self.resource('gateway_sa', ['iam', 'service-account'], 'telegram-codex-gateway')
        db = self.resource('database', ['ydb', 'database'], 'telegram-codex', [
            '--serverless', '--sls-enable-throttling-rcu', '--sls-throttling-rcu', '10',
            '--sls-provisioned-rcu', '0', '--sls-storage-size', '1GB'])
        database = self.yc('ydb', 'database', 'get', db)
        parsed = urllib.parse.urlparse(database['endpoint'])
        self.checkpoint('endpoint', parsed.scheme + '://' + parsed.netloc)
        self.checkpoint('database_path', urllib.parse.parse_qs(parsed.query)['database'][0])
        self.bind(['ydb', 'database'], db, 'ydb.editor', runtime)
        self.secrets()
        self.bind(['lockbox', 'secret'], self.state['secret'], 'lockbox.payloadViewer', runtime)
        package = STATE / 'function.zip'
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in ['domain.py', 'runtime.py', 'workspace.py', 'login.py']:
                z.write(ROOT / 'cloud' / name, 'cloud/' + name)
            if self.args.web:
                dist = ROOT / 'web' / 'dist'
                if not (dist / 'index.html').is_file():
                    raise RuntimeError('Build web assets first')
                manifest = {}
                for asset in sorted(dist.rglob('*')):
                    if not asset.is_file():
                        continue
                    relative = asset.relative_to(dist).as_posix()
                    route = '/' if relative == 'index.html' else '/' + relative
                    manifest[route] = {'file': relative, 'type': mimetypes.guess_type(relative)[0] or 'application/octet-stream'}
                    z.write(asset, 'cloud/static/' + relative)
                z.writestr('cloud/static/files.json', json.dumps(manifest))
            z.writestr('cloud/__init__.py', '')
            z.write(ROOT / 'cloud' / 'requirements.txt', 'requirements.txt')
        digest = hashlib.sha256()
        with zipfile.ZipFile(package) as archive:
            for name in sorted(archive.namelist()):
                digest.update(name.encode() + b'\0' + archive.read(name))
        digest.update(json.dumps({'project': self.args.project, 'settings': self.state['settings']}, sort_keys=True).encode())
        source_hash = digest.hexdigest()
        names = ('api', 'admin', 'authorizer', 'web_api', 'website') if self.args.web else ('webhook', 'api', 'worker', 'admin', 'authorizer')
        for name in names:
            fn = self.resource('fn_' + name, ['serverless', 'function'], 'telegram-codex-' + name.replace('_', '-'))
            self.bind(['serverless', 'function'], fn, 'functions.functionInvoker', gateway_sa) if name != 'admin' else None
            scaling_key = 'scaling:' + fn
            if self.state.get('version_' + name) and not self.state.get(scaling_key):
                self.yc('serverless', 'function', 'set-scaling-policy', fn, '--tag', '$latest',
                        '--zone-instances-limit', '1', '--zone-requests-limit', '2')
                self.checkpoint(scaling_key, True)
            if self.state.get('version_hash_' + name) == source_hash:
                continue
            env = {'OWNER_USERNAME': self.args.owner, 'ALLOWED_USERNAMES': '|'.join(self.args.allowed),
                   'THREAD_ID': self.args.thread, 'PROJECT_ID': self.args.project, 'CLIENT_KEY_HASH': self.state['client_hash'],
                   'YDB_ENDPOINT': self.state['endpoint'], 'YDB_DATABASE': self.state['database_path']}
            flags = []
            if name in ('webhook', 'worker', 'admin', 'web_api'):
                keys = ['WEBHOOK_SECRET'] if name == 'webhook' else ['TELEGRAM_BOT_TOKEN']
                if name == 'admin': keys.append('WEBHOOK_SECRET')
                for key in keys:
                    flags += ['--secret', 'id=' + self.state['secret'] + ',version-id=' + self.state['secret_version'] + ',key=' + key + ',environment-variable=' + key]
            version = self.yc('serverless', 'function', 'version', 'create', '--function-id', fn,
                '--runtime', 'python312', '--entrypoint', 'cloud.runtime.' + name,
                '--source-path', str(package), '--service-account-id', runtime,
                '--memory', '256MB', '--execution-timeout', '60s', '--concurrency', '1',
                '--environment', ','.join(k + '=' + v for k, v in env.items()), '--no-logging', *flags)
            self.checkpoint('version_' + name, version['id'])
            if not self.state.get(scaling_key):
                self.yc('serverless', 'function', 'set-scaling-policy', fn, '--tag', '$latest',
                        '--zone-instances-limit', '1', '--zone-requests-limit', '2')
                self.checkpoint(scaling_key, True)
            self.checkpoint('version_hash_' + name, source_hash)
            print('Function ready:', name, flush=True)
        spec = {'openapi': '3.0.0', 'info': {'title': 'Telegram Codex bridge', 'version': '1'}, 'paths': {},
                'components': {'securitySchemes': {'client': {'type': 'http', 'scheme': 'bearer',
                'x-yc-apigateway-authorizer': {'type': 'function', 'function_id': self.state['fn_authorizer'],
                 'service_account_id': gateway_sa, 'authorizer_result_ttl_in_seconds': 1}}}}}
        routes = [('/health', 'get', 'api'), ('/telegram/webhook', 'post', 'webhook'),
                ('/v1/inbox/claim', 'post', 'api'), ('/v1/inbox/ack', 'post', 'api'), ('/v1/replies', 'post', 'api')]
        if self.args.web:
            routes += [(path, 'get', 'website') for path in manifest]
            routes += [('/web/login/config', 'get', 'web_api')]
            routes += [(path, 'post', 'web_api') for path in ('/web/login/session','/web/state','/web/messages','/web/decisions','/web/grants')]
            routes += [(path, 'post', 'api') for path in ('/v2/catalog','/v2/inbox/claim','/v2/inbox/ack','/v2/responses','/v2/login-keys')]
        for path, method, name in routes:
            operation = {'responses': {'200': {'description': 'OK'}}, 'x-yc-apigateway-integration': {
                'type': 'cloud_functions', 'function_id': self.state['fn_' + name], 'tag': '$latest',
                'service_account_id': gateway_sa, 'payload_format_version': '1.0'}}
            if path.startswith(('/v1/', '/v2/')):
                operation['security'] = [{'client': []}]
            spec['paths'][path] = {method: operation}
        spec_path = STATE / 'gateway.json'
        save(spec_path, spec)
        gateway = self.resource('gateway', ['serverless', 'api-gateway'], 'telegram-codex',
                                ['--spec', str(spec_path), '--no-logging'])
        self.yc('serverless', 'api-gateway', 'update', gateway, '--spec', str(spec_path), '--no-logging')
        gateway_info = self.yc('serverless', 'api-gateway', 'get', gateway)
        self.checkpoint('url', 'https://' + gateway_info['domain'])
        initialized = self.invoke({'action': 'initialize_web' if self.args.web else 'initialize'})
        if not initialized.get('ok'):
            raise RuntimeError('Cloud initialization failed: ' + initialized.get('category', 'unknown') + '/' + initialized.get('reason', 'unknown'))
        print('Cloud login ready' if self.args.web else 'Cloud Telegram connection: ' + str(initialized.get('bot')), flush=True)
        save(STATE / 'cloud.json', {'url': self.state['url'], 'thread': self.args.thread,
             'key_file': str(STATE / 'cloud-key.env'), 'paused': True})
        if self.args.web:
            from cloud.login import public_keys
            result = self.invoke({'action':'login_keys', 'keys':public_keys(refresh=True), 'fetched_at':int(time.time())})
            if not result.get('ok'):
                raise RuntimeError('Public login key cache initialization failed')
            config_path = STATE / 'web.json'
            if not config_path.exists():
                save(config_path, {'url':self.state['url'], 'project_id':self.args.project,
                                  'key_file':str(STATE / 'cloud-key.env'), 'paused':False})
            print('Website provisioned:', self.state['url'], flush=True)
            return
        if 'timer' not in self.state:
            timer = self.yc('serverless', 'trigger', 'create', 'timer', '--name', 'telegram-codex-worker',
                '--cron-expression', '* * * * ? *', '--invoke-function-id', self.state['fn_worker'],
                '--invoke-function-service-account-id', gateway_sa, '--retry-attempts', '0')
            self.checkpoint('timer', timer['id'])
        print('Provisioned:', self.state['url'], flush=True)
        if self.args.activate:
            result = self.invoke({'action': 'activate', 'url': self.state['url'] + '/telegram/webhook'})
            if not result.get('ok'):
                raise RuntimeError('Webhook activation unconfirmed')
            self.checkpoint('activated', True)
            print('Telegram webhook activated; pending updates retained', flush=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', required=True)
    parser.add_argument('--thread', required=True)
    parser.add_argument('--owner', required=True)
    parser.add_argument('--allowed', nargs='+', required=True)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--web', action='store_true', help='Deploy standalone website without Bot API workers')
    parser.add_argument('--project', default='')
    args = parser.parse_args()
    try:
        Deploy(args).run()
    except Exception as exc:
        # Never expose remote response bodies, URLs containing secrets, or tracebacks.
        print('Deployment stopped:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__': sys.exit(main())
