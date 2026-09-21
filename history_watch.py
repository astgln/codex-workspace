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
from history_sync import sync_once


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
                failures = {}
                count = sync_once(API(config), catalog, config['project_id'], root, cache, failures)
                temp = cache_path.with_suffix('.tmp')
                temp.write_text(json.dumps(cache));temp.replace(cache_path)
                if count or args.once or bool(failures) != previous_error:
                    print(json.dumps({'status':'partial' if failures else 'synced',
                                      'messages':count,'failed_tasks':len(failures)}), flush=True)
                previous_error = bool(failures)
                if args.once and failures:
                    raise SystemExit(1)
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
