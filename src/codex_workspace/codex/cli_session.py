"""Read-only preflight for resuming an existing local Codex task.

The lock probe is advisory. Codex itself must acquire the writer lock at resume;
the collector must never delete locks or treat a failed resume as safe to resend.
"""
import fcntl
import json
import os
from pathlib import Path

from codex_workspace.agent.runtime_support import BridgeError
from codex_workspace.codex.rollout_response import UUID, locate


def writer_busy(home, thread):
    if not UUID.fullmatch(thread):
        raise BridgeError('Invalid task identity')
    path = Path(home) / 'thread-writer-locks' / (thread + '.lock')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def snapshot(home, thread, *, require_unowned=True):
    """Copy current task settings, without credentials or conversation content."""
    if require_unowned and writer_busy(home, thread):
        return {'status': 'busy', 'thread': thread}
    path = locate(Path(home) / 'sessions', thread)
    if path.is_symlink():
        raise BridgeError('Invalid session file')
    identity = False
    settings = None
    baseline = None
    context = None
    with path.open() as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                raise BridgeError('Incomplete session journal; retry preflight later') from None
            payload = record.get('payload', {})
            if record.get('type') == 'session_meta':
                if payload.get('id') != thread:
                    raise BridgeError('Session belongs to another task')
                identity = True
            if record.get('type') == 'turn_context':
                context = payload
            if record.get('type') != 'event_msg':
                continue
            if payload.get('type') == 'thread_settings_applied':
                if payload.get('thread_id') not in (None, thread):
                    raise BridgeError('Settings belong to another task')
                settings = payload.get('thread_settings')
                context = None  # Earlier context cannot establish current roots.
            if payload.get('type') == 'task_started':
                baseline = payload.get('turn_id')
    if not identity or not isinstance(settings, dict):
        raise BridgeError('Missing task identity or persisted settings')
    if baseline is not None and (not isinstance(baseline, str) or not UUID.fullmatch(baseline)):
        raise BridgeError('Invalid baseline turn')
    if 'runtime_workspace_roots' not in settings and isinstance(context,dict):
        roots=context.get('workspace_roots')
        if (context.get('turn_id') == baseline and context.get('cwd') == settings.get('cwd')
                and context.get('permission_profile') == settings.get('permission_profile')
                and isinstance(roots,list) and roots
                and all(isinstance(root,str) and Path(root).is_absolute() for root in roots)):
            settings={**settings,'runtime_workspace_roots':list(dict.fromkeys(roots))}
    required = ('model', 'model_provider_id', 'reasoning_effort', 'approval_policy',
                'approvals_reviewer', 'permission_profile', 'cwd', 'runtime_workspace_roots')
    if any(key not in settings for key in required):
        raise BridgeError('Incomplete persisted task settings')
    if require_unowned and writer_busy(home, thread):
        return {'status': 'busy', 'thread': thread}
    return {'status': 'ready', 'thread': thread, 'baseline': baseline,
            'settings': {key: settings[key] for key in required +
                         ('service_tier', 'reasoning_summary', 'personality',
                          'collaboration_mode', 'disabled_plugin_ids') if key in settings}}


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if type(value) is bool:
        return 'true' if value else 'false'
    if isinstance(value, list):
        return '[' + ','.join(toml_value(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{' + ','.join(toml_value(k)+'='+toml_value(v) for k,v in value.items()) + '}'
    raise BridgeError('Unsupported CLI setting value')


def command(executable, state):
    """Use a per-invocation named profile; never rewrite the user's config."""
    if state.get('status') != 'ready':
        raise BridgeError('Task is not ready')
    settings = state['settings']
    policy = settings['permission_profile']
    if policy.get('type') != 'managed' or policy.get('file_system', {}).get('type') != 'restricted':
        raise BridgeError('CLI bridge requires restricted managed permissions')
    filesystem = {}
    for entry in policy['file_system']['entries']:
        target = entry['path']
        if target['type'] == 'path':
            path = target['path']
            if not Path(path).is_absolute():
                raise BridgeError('Relative permission path')
        elif target['type'] == 'special' and target['value'].get('kind') in ('root', 'minimal', 'tmpdir', 'slash_tmp'):
            path = ':' + target['value']['kind']
        else:
            raise BridgeError('Unsupported permission target')
        if entry['access'] not in ('read','write','deny') or (path in filesystem and filesystem[path] != entry['access']):
            raise BridgeError('Ambiguous filesystem permissions')
        # Keep explicit read restrictions even for absent protected paths.
        filesystem[path] = entry['access']
    if policy.get('network') not in ('enabled','restricted'):
        raise BridgeError('Unsupported network policy')
    profile = {'filesystem': filesystem,
               'network': {'enabled': policy['network'] == 'enabled'},
               'workspace_roots': {p: True for p in settings['runtime_workspace_roots']}}
    config = {'permissions.workspace_bridge': profile,
              'default_permissions': 'workspace_bridge',
              'model': settings['model'], 'model_provider': settings['model_provider_id'],
              'model_reasoning_effort': settings['reasoning_effort'],
              'approval_policy': settings['approval_policy'],
              'approvals_reviewer': settings['approvals_reviewer']}
    for source, target in [('service_tier','service_tier'), ('reasoning_summary','model_reasoning_summary'),
                           ('personality','personality')]:
        if settings.get(source) is not None:
            config[target] = settings[source]
    if settings.get('disabled_plugin_ids'):
        raise BridgeError('Disabled task plugins require explicit CLI mapping')
    mode = settings.get('collaboration_mode')
    if mode and mode.get('mode') not in ('default', None):
        raise BridgeError('CLI bridge cannot preserve this collaboration mode')
    args = [str(executable), 'exec', '--skip-git-repo-check', '--cd', settings['cwd']]
    for key, value in config.items():
        args += ['-c', key+'='+toml_value(value)]
    return args + ['resume', state['thread'], '--json', '-']
