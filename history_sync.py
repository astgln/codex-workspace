"""Independent history checkpoints and retryable quota publication."""
from runtime_support import BridgeError
from history_client import publish
from rollout_history import read_public, READER_VERSION
from rollout_response import locate

RECOVERABLE = (BridgeError, OSError, ValueError, KeyError)


def sync_thread(api, ident, root, cache, pending):
    path = locate(root, ident)
    stat = path.stat()
    fingerprint = [stat.st_dev, stat.st_ino]
    previous = cache.get(ident, {})
    compatible = previous.get('reader_version') == READER_VERSION and previous.get('checkpoint_version') == 1
    offset = previous.get('offset', 0) if compatible and previous.get('file') == fingerprint else 0
    if offset > stat.st_size:
        offset = 0
    if offset == stat.st_size:
        if ident in pending:
            publish(api, {'thread': {'id': ident}, 'turns': []}, 'latest')
        return 0
    read = read_public(path, ident, offset)
    publish(api, read, 'older' if offset == 0 else 'latest')
    checkpoint = {'checkpoint_version':1, 'reader_version':READER_VERSION,
                  'file':fingerprint, 'offset':read['source_offset']}
    quota = read.get('weekly_quota') or previous.get('pending_quota')
    if quota:
        checkpoint['pending_quota'] = quota
    cache[ident] = checkpoint
    return sum(len(turn['items']) for turn in read['turns'])


def sync_once(api, catalog, project, root, cache, failures=None, service_failures=None):
    failures = failures if failures is not None else {}
    service_failures = service_failures if service_failures is not None else {}
    projects = {p['id'] for p in catalog.get('projects', [{'id':project}])}
    threads = catalog.get('threads', [])
    # Validate the entire scope before publishing any task, even on partial passes.
    if catalog.get('project_id') != project or any(t.get('project_id') not in projects for t in threads):
        raise BridgeError('Project mismatch')
    pending = set()
    try:
        response = api.call('/v2/history/pending', {})
        entries = response.get('threads') if isinstance(response, dict) else None
        if not isinstance(entries, list) or any(not isinstance(item, dict) or
                not isinstance(item.get('thread'), str) for item in entries):
            raise ValueError('Invalid pending history response')
        pending = {item['thread'] for item in entries}
    except RECOVERABLE:
        # This endpoint only asks for refreshes of otherwise idle journals.
        # Its failure must not suppress changed journals or retained quota retries.
        service_failures['pending'] = 'pending_unavailable'
    count = 0
    for thread in threads:
        ident = thread['id']
        try:
            count += sync_thread(api, ident, root, cache, pending)
        except RECOVERABLE:
            failures[ident] = 'history_unavailable'
    # Quota failure does not roll back uploaded history or force a journal replay.
    for thread in threads:
        ident = thread['id']
        checkpoint = cache.get(ident, {})
        quota = checkpoint.get('pending_quota')
        if quota:
            try:
                api.call('/v2/usage', quota)
                del checkpoint['pending_quota']
            except RECOVERABLE:
                failures.setdefault(ident, 'quota_unavailable')
    return count
