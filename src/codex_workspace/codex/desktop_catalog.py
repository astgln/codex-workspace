"""Read desktop's explicit project assignments; never infer access from paths.

This is a version-checked, read-only adapter to local desktop persistence, not a
public Codex API. Unknown layouts fail closed and retain the last good snapshot.
"""
from contextlib import closing
import json
import re
import sqlite3
from codex_workspace.agent.runtime_support import BridgeError
from codex_workspace.codex.cli_session import writer_busy

ID = re.compile(r'[a-zA-Z0-9-]{1,80}')


def discover(home, previous, cache):
    state_path = home / '.codex-global-state.json'
    raw = state_path.read_bytes()
    state = json.loads(raw)
    if not isinstance(state, dict):
        raise BridgeError('Invalid desktop state')
    projects = state.get('local-projects')
    assignments = state.get('thread-project-assignments')
    excluded = state.get('projectless-thread-ids')
    if not isinstance(projects, dict) or not isinstance(assignments, dict) or not isinstance(excluded, list) or any(not isinstance(x, str) for x in excluded):
        raise BridgeError('Unsupported desktop catalog schema')
    entries = []
    for ident, project in projects.items():
        if (not ID.fullmatch(ident) or not isinstance(project, dict) or project.get('id') != ident
                or not isinstance(project.get('name'), str) or not 1 <= len(project['name']) <= 200):
            raise BridgeError('Invalid desktop project')
        entries.append({'id': ident, 'title': project['name']})
    prior = {t['id']: t for t in previous['threads']}
    threads = []
    try:
        with closing(sqlite3.connect((home / 'state_5.sqlite').as_uri() + '?mode=ro', uri=True)) as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(threads)')}
            stamp = 'COALESCE(updated_at_ms / 1000.0, updated_at, 0)' if {'updated_at_ms', 'updated_at'} <= columns else 'updated_at' if 'updated_at' in columns else '0'
            rows = db.execute(f'SELECT id,name,source,{stamp} FROM threads WHERE archived=0').fetchall()
    except sqlite3.Error:
        raise BridgeError('Desktop catalog database unavailable') from None
    for ident, title, source, updated_at in rows:
        assignment = assignments.get(ident)
        if assignment is None or ident in excluded:
            continue
        if not isinstance(assignment, dict):
            raise BridgeError('Invalid desktop assignment')
        if assignment.get('projectKind') != 'local':
            continue
        project = assignment.get('projectId')
        if project not in projects:
            raise BridgeError('Unresolved desktop project')
        # Unnamed drafts and internal agent sessions are not sidebar tasks.
        if not title or source not in ('vscode', 'cli', 'exec'):
            continue
        if not isinstance(title, str) or len(title) > 200:
            raise BridgeError('Invalid desktop task title')
        activity = cache.get(ident, {}).get('activity', {})
        status = 'unknown'
        if activity.get('state') == 'idle':
            status = 'idle'
        elif activity.get('state') == 'active' and writer_busy(home, ident):
            status = 'active'
        threads.append({'id': ident, 'title': title, 'project_id': project,
                        'updated_at': updated_at or 0, 'status': status, 'read_only': prior.get(ident, {}).get('read_only') is True})
    # A concurrent project move must not produce a mixed snapshot.
    if state_path.read_bytes() != raw:
        raise BridgeError('Desktop catalog changed during read')
    if len(entries) > 100 or len(threads) > 1000:
        raise BridgeError('Desktop catalog exceeds transport limits')
    return {'project_id': previous['project_id'], 'projects': sorted(entries, key=lambda p:p['id']),
            'threads': sorted(threads, key=lambda t:t['id'])}


def refresh(api, path, home, cache):
    previous = json.loads(path.read_text())
    catalog = discover(home, previous, cache)
    if catalog != previous:
        # Publish before installing the common worker/history snapshot.
        api.call('/v2/catalog', catalog)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(catalog, ensure_ascii=False))
        temporary.replace(path)
    return catalog
