"""Initialize a new installation; never overwrite an existing state directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urlsplit
from codex_workspace.devices.e2ee_admin import write_private
from codex_workspace.paths import state_directory


def initialize(directory, origin, folder, gateway, branch):
    parsed=urlsplit(origin)
    if (parsed.scheme!='https' or not parsed.hostname or
        not parsed.hostname.endswith('.apigw.yandexcloud.net') or
        parsed.netloc!=parsed.hostname or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Use the exact HTTPS Yandex API Gateway origin without a trailing slash')
    if not all(re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',x) for x in (folder,gateway)):
        raise ValueError('Invalid cloud identifier')
    if branch not in ('main','experimental/multi-user'):
        raise ValueError('Unsupported release branch')
    directory=Path(directory).expanduser().absolute()
    # No exist_ok: partial setups, symlinks and existing installations are refused.
    directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    project=secrets.token_hex(16);token=secrets.token_urlsafe(48)
    def save(name,value):write_private(directory/name,json.dumps(value)+'\n')
    write_private(directory/'client-key.env','BRIDGE_CLIENT_KEY='+token+'\n')
    save('web.json',{'url':origin,'key_file':str(directory/'client-key.env'),'paused':False,'project_id':project})
    save('history-catalog.json',{'project_id':project,'projects':[],'threads':[]})
    save('deployment.json',{'folder':folder,'gateway':gateway,'project':project,'settings':{'owner':'owner'},
        'client_hash':hashlib.sha256(token.encode()).hexdigest(),'url':origin,'release_branch':branch})
    env={**os.environ,'CODEX_WORKSPACE_STATE':str(directory)}
    subprocess.run([sys.executable,'-m','codex_workspace','devices','--state',str(directory),'init',
        '--origin',origin,'--catalog',str(directory/'history-catalog.json'),
        '--package',str(directory/'recovery.json'),'--code-file',str(directory/'recovery-code.txt')],env=env,check=True)
    subprocess.run([sys.executable,'-m','codex_workspace','devices','--state',str(directory),'auth-pin',
        '--output',str(directory/'device-auth.json')],env=env,check=True)
    write_private(directory/'e2ee-required','codex-workspace/e2ee/v1\n')
    return directory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=state_directory())
    parser.add_argument('--origin',required=True)
    parser.add_argument('--folder',required=True)
    parser.add_argument('--gateway',required=True)
    parser.add_argument('--branch',choices=['main','experimental/multi-user'],default='main')
    args=parser.parse_args();os.umask(0o077)
    try:initialize(args.state,args.origin,args.folder,args.gateway,args.branch)
    except (OSError,ValueError,subprocess.CalledProcessError):
        raise SystemExit('Setup stopped. Existing state is never overwritten; partial state is retained for inspection. No secrets printed.') from None
    print('Fresh encrypted installation prepared. Store the recovery package and code separately; then provision and deploy the relay.')

if __name__=='__main__':main()
