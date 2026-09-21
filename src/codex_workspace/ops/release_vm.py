#!/usr/bin/env python3
"""Build and publish a private immutable VM release over SSH/SCP."""
import argparse
import base64
import hashlib
import io
import json
import mimetypes
import tarfile
import time
import os
import re
import subprocess
import shlex
import urllib.request
from pathlib import Path
from codex_workspace.ops.deploy import Deploy, STATE, ROOT, save
from codex_workspace.agent.runtime_support import NoRedirect


def deployment():
    state=json.loads((STATE/'deployment.json').read_text())
    return Deploy(argparse.Namespace(folder=state['folder'],thread=state['settings']['thread'],allowed=state['settings']['allowed'],
        owner=state['settings']['owner'],project=state['project']))


def verify_pinned_host_key(path, host):
    if path.is_symlink() or not path.is_file():raise RuntimeError('Pinned SSH host key is unavailable')
    info=path.stat()
    if info.st_uid!=os.getuid() or info.st_mode&0o022 or info.st_nlink!=1 or info.st_size>1024:
        raise RuntimeError('Unsafe SSH host key file')
    fields=path.read_text().split()
    if len(fields)!=3 or fields[:2]!=[host,'ssh-ed25519']:
        raise RuntimeError('Pinned SSH host identity differs from deployment target')
    try:raw=base64.b64decode(fields[2],validate=True)
    except ValueError:raise RuntimeError('Invalid pinned SSH host key') from None
    if len(raw)!=51 or not raw.startswith(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'):
        raise RuntimeError('Invalid pinned SSH host key')


def release_files(root):
    """Explicit source/resource allowlist; never package local state or tests."""
    files={}
    for name in ('pyproject.toml','README.md','LICENSE','web/licenses/codex-webui-MIT.txt'):
        files[name]=(root/name).read_bytes()
    for directory,extensions in (('src/codex_workspace',{'.py'}),('ops/server',{'.sh','.service'})):
        for path in sorted((root/directory).rglob('*')):
            if path.is_file() and path.suffix in extensions:
                files[path.relative_to(root).as_posix()]=path.read_bytes()
    manifest={};dist=root/'web/dist'
    if not (dist/'index.html').is_file():raise RuntimeError('Build the frontend first')
    for path in sorted(dist.rglob('*')):
        if path.is_file():
            relative=path.relative_to(dist).as_posix()
            files['static/'+relative]=path.read_bytes()
            manifest['/' if relative=='index.html' else '/'+relative]={'file':relative,'type':mimetypes.guess_type(relative)[0] or 'application/octet-stream'}
    files['static/files.json']=json.dumps(manifest).encode()
    return files


def publish(ssh_interface=None, use_pinned_host_key=False):
    if ssh_interface is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,31}", ssh_interface):
        raise RuntimeError("Invalid SSH interface")
    if ROOT is None:raise RuntimeError('Set CODEX_WORKSPACE_SOURCE to the release checkout')
    d=deployment();s=d.state
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    expected=s.get('release_branch','experimental/multi-user')
    if branch!=expected:
        raise RuntimeError('Deployment branch mismatch; use the configured checkout')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip():
        raise RuntimeError('Commit tracked source changes before deployment')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    files=release_files(ROOT)
    files['release.json']=json.dumps({'branch':branch,'commit':commit}).encode()
    settings={'OWNER_USERNAME':s['settings']['owner'],
        'CLIENT_KEY_HASH':s['client_hash'],'PROJECT_ID':s['project'],'PUBLIC_ORIGIN':s['url']}
    settings['auth_pin']=json.loads((STATE/'device-auth.json').read_text())
    files['settings.json']=json.dumps(settings).encode()
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz') as tar:
        for name,data in sorted(files.items()):
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o600 if name=='migration.json' else 0o644
            tar.addfile(entry,io.BytesIO(data))
    data=archive.getvalue();digest=hashlib.sha256(data).hexdigest()
    artifact=STATE/'vm-release.tar.gz'
    fd=os.open(artifact,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as output:output.write(data)
    known=STATE/'vm-known-hosts'
    if use_pinned_host_key:
        # Explicit reuse of an already authenticated exact-host pin. SSH still
        # verifies the live key; no TOFU, key replacement or host-check bypass.
        verify_pinned_host_key(known,s['vm_public_ip'])
    else:
        serial=subprocess.run(['yc','compute','instance','get-serial-port-output',s['vm_instance'],
            '--folder-id',s['folder'],'--format','json'],capture_output=True,text=True,check=True,timeout=45)
        try:contents=json.loads(serial.stdout)['contents']
        except (ValueError,KeyError,TypeError):contents=serial.stdout
        keys=re.findall(r'(ssh-ed25519 [A-Za-z0-9+/=]+)',contents)
        if not keys:raise RuntimeError('No authenticated SSH host key')
        known.write_text(s['vm_public_ip']+' '+keys[-1]+'\n')
    options=['-i',str(STATE/'web-vm-ed25519'),'-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
             '-o','UserKnownHostsFile='+str(known),'-o','ConnectTimeout=15']
    if ssh_interface:
        options += ['-o', 'BindInterface='+ssh_interface]
    host='bridge@'+s['vm_public_ip']
    def run(command):
        result=subprocess.run(command,capture_output=True,text=True)
        if result.returncode:raise RuntimeError('SSH deployment command failed; inspect connectivity or service status')
        return result.stdout
    run(['ssh',*options,host,'true'])
    remote='/home/bridge/workspace-'+digest+'.tar.gz'
    run(['scp',*options,str(artifact),host+':'+remote])
    release='/opt/codex-workspace/releases/'+digest
    command=' && '.join([
        'test "$(sha256sum '+shlex.quote(remote)+' | cut -d " " -f 1)" = '+shlex.quote(digest),
        '(sudo systemctl disable --now codex-workspace-update.timer 2>/dev/null || true)',
        '(sudo systemctl stop codex-workspace-update.service 2>/dev/null || true)',
        'sudo mkdir -p '+shlex.quote(release),
        'sudo tar -xzf '+shlex.quote(remote)+' -C '+shlex.quote(release)+' --no-same-owner',
        'sudo sh '+shlex.quote(release+'/ops/server/install.sh')+' '+shlex.quote(release),
        'rm -- '+shlex.quote(remote)])
    run(['ssh',*options,host,command])
    # Health is checked over the same authenticated SSH transport.
    run(['ssh',*options,host,'python3 -c '+shlex.quote("import json,time,urllib.request; time.sleep(2); r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5)); assert r['mode']=='standalone-web'; print('VM health verified')")])
    d.checkpoint('vm_release',digest);d.checkpoint('vm_ssh_deployed',True)
    print('Release installed and checked over SSH:',digest[:16],flush=True)


def gateway(cutover=False):
    if ROOT is None:raise RuntimeError('Set CODEX_WORKSPACE_SOURCE to the release checkout')
    d=deployment();s=d.state
    def operation(path):
        return {'responses':{'200':{'description':'Web application response'}},
            'x-yc-apigateway-integration':{'type':'http','url':'http://'+s['vm_private_ip']+':8080'+path,
                'headers':{'*':'*'},'query':{'*':'*'},'timeouts':{'connect':5,'read':30}}}
    if cutover:
        root=operation('/');wild=operation('/{path}')
        wild['parameters']=[{'name':'path','in':'path','required':True,'schema':{'type':'string'}}]
        spec={'openapi':'3.0.0','info':{'title':'Codex Workspace','version':'2'},
              'paths':{'/':{'x-yc-apigateway-any-method':root},'/{path+}':{'x-yc-apigateway-any-method':wild}}}
    else:
        source=STATE/'gateway-migration.json'
        spec=json.loads((source if source.exists() else STATE/'gateway.json').read_text())
        spec['paths']['/vm-health']={'get':operation('/health')}
    path=STATE/('gateway-vm.json' if cutover else 'gateway-vm-probe.json');save(path,spec)
    flags=['--network-id',s['vm_network']]
    d.yc('serverless','api-gateway','update',s['gateway'],'--spec',str(path),'--no-logging',*flags)
    if cutover:d.checkpoint('vm_app_installed',True)
    print('Gateway switched to VM' if cutover else 'VM health probe routed',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['publish','probe','cutover'])
    parser.add_argument('--ssh-interface',help='Bind SSH/SCP to an existing interface; does not modify routes')
    parser.add_argument('--use-pinned-host-key',action='store_true',help='Use the existing exact-host SSH pin without querying Compute API')
    args=parser.parse_args()
    try:
        if args.action=='publish':publish(args.ssh_interface,args.use_pinned_host_key)
        else:gateway(args.action=='cutover')
    except Exception as exc:
        print('VM release stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)
        raise SystemExit(1)
        raise SystemExit(1)
