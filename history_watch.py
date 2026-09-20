#!/usr/bin/env python3
"""Continuously upload only public history from explicitly authorized tasks.

This service cannot send prompts, launch Codex, or modify its configuration.
"""
import argparse
import json
import os
from pathlib import Path
import time
from bridge import BridgeError, exclusive
from cloud_client import API, STATE
from history_client import publish
from rollout_history import read_public
from rollout_response import locate


def sync_once(api, catalog, project, root, cache):
    if catalog.get('project_id') != project:
        raise BridgeError('Project mismatch')
    count = 0
    pending = {t['thread'] for t in api.call('/v2/history/pending', {}).get('threads', [])}
    for thread in catalog.get('threads', []):
        if thread.get('project_id') not in {p['id'] for p in catalog.get('projects', [{'id':project}])}:
            raise BridgeError('Project mismatch')
        ident = thread['id']
        path = locate(root, ident)
        stat = path.stat()
        fingerprint = [stat.st_dev, stat.st_ino]
        previous = cache.get(ident, {})
        offset = previous.get('offset', 0) if previous.get('file') == fingerprint else 0
        if offset > stat.st_size:
            offset = 0
        if offset == stat.st_size:
            if ident in pending:
                publish(api, {'thread': {'id': ident}, 'turns': []}, 'latest')
            continue
        read = read_public(path, ident, offset)
        publish(api, read, 'older' if offset == 0 else 'latest')
        if read.get('weekly_quota'):
            api.call('/v2/usage', read['weekly_quota'])
        cache[ident] = {'file': fingerprint, 'offset': read['source_offset']}
        count += sum(len(t['items']) for t in read['turns'])
    return count


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=STATE)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--interval', type=int, default=10)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.interval <= 300:
        parser.error('interval must be 1..300 seconds')
    cache_path = args.state / 'history-watch.json'
    root = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'sessions'
    # Separate lock: history must keep updating during a long CLI request.
    lock_dir = args.state / 'history-transport'
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with exclusive(lock_dir):
        previous_error = False
        while True:
            try:
                config = json.loads((args.state/'web.json').read_text())
                if config.get('paused', True):
                    return
                catalog = json.loads(args.catalog.read_text())
                cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
                count = sync_once(API(config), catalog, config['project_id'], root, cache)
                temp = cache_path.with_suffix('.tmp')
                temp.write_text(json.dumps(cache));temp.replace(cache_path)
                if count or args.once or previous_error:
                    print(json.dumps({'status':'synced','messages':count}), flush=True)
                previous_error = False
            except (BridgeError, OSError, ValueError, KeyError):
                if not previous_error:
                    print('{"status":"history_sync_failed","retry":true}', flush=True)
                previous_error = True
                if args.once:
                    raise SystemExit(1)
            if args.once:
                return
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
