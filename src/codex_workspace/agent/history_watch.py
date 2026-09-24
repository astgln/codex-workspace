#!/usr/bin/env python3
"""Continuously upload only public history from explicitly authorized tasks.

This service cannot send prompts, launch Codex, or modify its configuration.
"""
import argparse
import json
import os
from pathlib import Path
import time
from codex_workspace.agent.runtime_support import BridgeError, exclusive
from codex_workspace.agent.workspace_client import API, STATE
from codex_workspace.agent.history_sync import sync_once
from codex_workspace.codex.desktop_catalog import refresh


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
                cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
                api = API(config, state=args.state)
                from codex_workspace.agent.encryption_mode import encrypted_required
                if encrypted_required(args.state):
                    # Independent checkpoint prevents plaintext-era offsets skipping
                    # history during the first encrypted publication.
                    from codex_workspace.devices.key_vault import KeyVault
                    from codex_workspace.agent.sealed_history import EncryptedHistoryAPI
                    with KeyVault(args.state/'e2ee-keys.sqlite3') as vault:
                        encrypted_api=EncryptedHistoryAPI(api,vault)
                        sealed_cache_path=args.state/'encrypted-history-watch.json'
                        sealed_cache=json.loads(sealed_cache_path.read_text()) if sealed_cache_path.exists() else {}
                        catalog=refresh(encrypted_api,args.catalog,root.parent,sealed_cache)
                        encrypted_api.call('/v2/catalog',catalog)
                        failures={};service_failures={}
                        count=sync_once(encrypted_api,catalog,config['project_id'],root,sealed_cache,failures,service_failures)
                        temporary=sealed_cache_path.with_suffix('.tmp')
                        temporary.write_text(json.dumps(sealed_cache));temporary.replace(sealed_cache_path)
                        if failures or service_failures:
                            raise BridgeError('Encrypted history sync incomplete')
                    if args.once:return
                    time.sleep(args.interval)
                    continue
                catalog = refresh(api, args.catalog, root.parent, cache)
                failures = {}
                service_failures = {}
                count = sync_once(api, catalog, config['project_id'], root, cache, failures, service_failures)
                temp = cache_path.with_suffix('.tmp')
                temp.write_text(json.dumps(cache));temp.replace(cache_path)
                partial = bool(failures or service_failures)
                if count or args.once or partial != previous_error:
                    print(json.dumps({'status':'partial' if partial else 'synced',
                                      'messages':count,'failed_tasks':len(failures),'failed_services':sorted(service_failures)}), flush=True)
                previous_error = partial
                if args.once and partial:
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
