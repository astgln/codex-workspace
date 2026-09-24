#!/usr/bin/env python3
"""Outbound service loop for queued requests to existing local CLI tasks."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from codex_workspace.agent.runtime_support import BridgeError, exclusive
from codex_workspace.agent.workspace_client import API, STATE
from codex_workspace.agent.local_queue import Queue
from codex_workspace.agent.worker_dispatch import dispatch_one
from codex_workspace.agent.worker_lifecycle import shutdown_event
from codex_workspace.agent.worker_health import publish as publish_health


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=STATE)
    parser.add_argument('--codex',type=Path)
    parser.add_argument('--transport',choices=('cli',),default='cli')
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--interval',type=int,default=10)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if args.transport=='cli' and args.codex is None:
        parser.error('--codex is required for CLI transport')
    if not 1<=args.interval<=300:
        parser.error('interval must be 1..300 seconds')
    home=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))
    with shutdown_event() as stop:
        return serve(args, home, stop)


def serve(args, home, stop):
    previous_result=None
    try:
        while not stop.is_set():
            config=json.loads((args.state/'web.json').read_text())
            if config.get('paused',True):
                return 0
            catalog=json.loads(args.catalog.read_text())
            if catalog.get('project_id') != config['project_id']:
                raise BridgeError('Project mismatch')
            with exclusive(args.state):
                from codex_workspace.agent.encryption_mode import encrypted_required
                encrypted = encrypted_required(args.state)
                vault = None
                queue = None
                try:
                    api=API(config, state=args.state)
                    if encrypted:
                        from codex_workspace.devices.key_vault import KeyVault
                        from codex_workspace.agent.sealed_runtime import SealedRuntime
                        vault=KeyVault(args.state/'e2ee-keys.sqlite3')
                        queue=SealedRuntime(args.state,vault,api,catalog)
                        queue.tick()
                        result=dispatch_one(queue,home,args.codex,catalog,api=queue.api,should_stop=stop.is_set)
                        queue.tick()
                        queue.health(result)
                    else:
                        queue=Queue(args.state)
                        queue.tick(api)
                        result=dispatch_one(queue,home,args.codex,catalog,api=api,should_stop=stop.is_set)
                        queue.tick(api)
                        publish_health(api, result)
                finally:
                    if queue is not None:
                        if encrypted:queue.close()
                        else:queue.db.close()
                    if vault is not None:vault.db.close()
            status_path=args.state/'cli-worker-status.json'
            temporary=status_path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'updated_at':int(time.time()),'pid':os.getpid(),**result}))
            temporary.replace(status_path)
            if args.once or (result['status']!='idle' and result!=previous_result):
                print(json.dumps(result),flush=True)
            previous_result=result
            if args.once:
                return 0
            stop.wait(args.interval)
        return 0
    except (BridgeError,OSError,ValueError,KeyError) as exc:
        print(str(exc) if isinstance(exc,BridgeError) else 'CLI collector error; details hidden',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
