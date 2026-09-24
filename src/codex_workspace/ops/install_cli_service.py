#!/usr/bin/env python3
"""Install the outbound CLI collector as a per-user macOS service."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from codex_workspace.paths import state_directory
STATE = state_directory()


def definition(python, codex, catalog, state, kind="requests"):
    if kind not in ("requests","history"):raise ValueError("Unknown service")
    label="net.codex-workspace."+kind
    log_name="cli-worker" if kind=="requests" else "history-watch"
    command=(["agent","run","--transport","cli","--codex",str(codex)] if kind=="requests" else ["history","watch"])
    return {'Label':label,
        'ProgramArguments':[str(python),'-m','codex_workspace',*command,'--catalog',str(catalog),'--state',str(state)],
        'WorkingDirectory':str(state),'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':30,
        'EnvironmentVariables':{'CODEX_WORKSPACE_STATE':str(state),'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StandardOutPath':str(state/(log_name+'.log')),'StandardErrorPath':str(state/(log_name+'.err')),'Umask':63}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=['requests','history'],default='requests')
    parser.add_argument('--codex',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--state',type=Path,default=STATE)
    args=parser.parse_args()
    if sys.platform!='darwin':parser.error('This installer requires macOS')
    codex=args.codex.resolve();catalog=args.catalog.resolve();state=args.state.resolve()
    if not codex.is_file() or not os.access(codex,os.X_OK) or not catalog.is_file() or not (state/'web.json').is_file():
        parser.error('Missing executable, catalog or configured web collector')
    target=Path.home()/'Library/LaunchAgents'/f'net.codex-workspace.{args.kind}.plist'
    if target.exists():parser.error('Service already exists; inspect it before updating')
    state.mkdir(mode=0o700,exist_ok=True)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as stream:plistlib.dump(definition(Path(sys.executable),codex,catalog,state,args.kind),stream)
    subprocess.run(['launchctl','bootstrap',f'gui/{os.getuid()}',str(target)],check=True)
    print('Outbound '+args.kind+' collector installed')


if __name__=='__main__':main()
