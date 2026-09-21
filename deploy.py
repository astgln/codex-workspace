"""Private VM deployment state and Yandex Cloud resource helpers."""
import json
import os
import re
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.local'


def save(path, data):
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream)
    temp.replace(path)


class Deploy:
    def __init__(self, args):
        self.args = args
        STATE.mkdir(mode=0o700, exist_ok=True)
        self.path = STATE / 'deployment.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        if self.state.get('folder', args.folder) != args.folder:
            raise RuntimeError('Deployment belongs to another folder')
        if not re.fullmatch(r'[a-z0-9_]{5,32}', args.owner):
            raise RuntimeError('Invalid account username')
        if self.state.get('settings', {}).get('owner', args.owner) != args.owner:
            raise RuntimeError('Account change requires explicit migration')
        if self.state.get('project', args.project) != args.project:
            raise RuntimeError('Catalog scope changed; explicit migration required')
        self.state.update(settings={'owner': args.owner}, project=args.project, folder=args.folder)

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


    def bind(self, group, resource, role, account):
        key = 'binding:' + resource + ':' + role + ':' + account
        if not self.state.get(key):
            self.yc(*group, 'add-access-binding', resource, '--role', role, '--service-account-id', account)
            self.checkpoint(key, True)
