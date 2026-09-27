"""Explicit, owner-approved local relocation; never supplied by the relay."""
import copy
import hashlib
import json
import os
from pathlib import Path
from codex_workspace.agent.runtime_support import BridgeError


def fingerprint(settings):
    value={k:settings[k] for k in ('cwd','runtime_workspace_roots','permission_profile')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def apply(state, directory):
    path=Path(directory)/'task-relocations.json'
    if not path.exists() and not path.is_symlink():return state
    info=path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise BridgeError('Unsafe local task relocation configuration')
    entry=json.loads(path.read_text()).get(state['thread'])
    if entry is None:return state
    settings=state['settings']
    if set(entry)!={'from','to','settings_sha256'} or fingerprint(settings)!=entry['settings_sha256'] or settings['cwd']!=entry['from']:
        raise BridgeError('Task settings changed; relocation requires review')
    old,new=Path(entry['from']),Path(entry['to'])
    if not old.is_absolute() or not new.is_absolute() or not new.is_dir() or new.resolve()!=new:
        raise BridgeError('Invalid relocated working directory')
    def move(value):
        p=Path(value)
        return str(new/p.relative_to(old)) if p.is_relative_to(old) else value
    result=copy.deepcopy(state);s=result['settings'];s['cwd']=str(new)
    s['runtime_workspace_roots']=[move(p) for p in s['runtime_workspace_roots']]
    for entry in s['permission_profile']['file_system']['entries']:
        if entry['path']['type']=='path':entry['path']['path']=move(entry['path']['path'])
    return result
