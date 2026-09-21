"""Private VM deployment state and Yandex Cloud resource helpers."""
import json
import os
import re
import subprocess
from pathlib import Path
from codex_workspace.paths import source_directory, state_directory
ROOT = Path(os.environ['CODEX_WORKSPACE_SOURCE']).expanduser().resolve() if os.environ.get('CODEX_WORKSPACE_SOURCE') else None
STATE = state_directory()


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


    def bind(self, group, resource, role, account):
        key = 'binding:' + resource + ':' + role + ':' + account
        if not self.state.get(key):
            self.yc(*group, 'add-access-binding', resource, '--role', role, '--service-account-id', account)
            self.checkpoint(key, True)
