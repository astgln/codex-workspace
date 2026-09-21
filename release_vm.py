#!/usr/bin/env python3
"""Build and publish a private immutable VM release over SSH/SCP."""
import argparse
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
from deploy import Deploy, STATE, ROOT, save
from runtime_support import NoRedirect


def deployment():
    state=json.loads((STATE/'deployment.json').read_text())
    return Deploy(argparse.Namespace(folder=state['folder'],
        owner=state['settings']['owner'],project=state['project']))


def publish(ssh_interface=None):
    if ssh_interface is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,31}", ssh_interface):
        raise RuntimeError("Invalid SSH interface")
    d=deployment();s=d.state
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    expected=s.get('release_branch','main')
    if branch!=expected:
        raise RuntimeError('Deployment branch mismatch; use the configured checkout')
    if subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True).strip():
        raise RuntimeError('Commit tracked source changes before deployment')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    files={'release.json':json.dumps({'branch':branch,'commit':commit}).encode()}
    for directory in ('cloud','server'):
        for path in (ROOT/directory).iterdir():
            if path.is_file() and path.suffix in ('.py','.txt','.sh','.service'):
                files[directory+'/'+path.name]=path.read_bytes()
    files['cloud/__init__.py']=b'';files['server/__init__.py']=b''
    manifest={};dist=ROOT/'web/dist'
    if not (dist/'index.html').is_file():raise RuntimeError('Build the frontend first')
    for path in sorted(dist.rglob('*')):
        if path.is_file():
            relative=path.relative_to(dist).as_posix()
            files['cloud/static/'+relative]=path.read_bytes()
            manifest['/' if relative=='index.html' else '/'+relative]={'file':relative,'type':mimetypes.guess_type(relative)[0] or 'application/octet-stream'}
    files['cloud/static/files.json']=json.dumps(manifest).encode()
    settings={'secret_id':s['secret'],'OWNER_USERNAME':s['settings']['owner'],
        'CLIENT_KEY_HASH':s['client_hash'],'PROJECT_ID':s['project'],'PUBLIC_ORIGIN':s['url']}
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
    # Trust the VM host key from authenticated Compute API boot output.
    serial=subprocess.run(['yc','compute','instance','get-serial-port-output',s['vm_instance'],
        '--folder-id',s['folder'],'--format','json'],capture_output=True,text=True,check=True)
    try:contents=json.loads(serial.stdout)['contents']
    except (ValueError,KeyError,TypeError):contents=serial.stdout
    keys=re.findall(r'(ssh-ed25519 [A-Za-z0-9+/=]+)',contents)
    if not keys:raise RuntimeError('No authenticated SSH host key')
    known=STATE/'vm-known-hosts';known.write_text(s['vm_public_ip']+' '+keys[-1]+'\n')
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
        'sudo sh '+shlex.quote(release+'/server/install.sh')+' '+shlex.quote(release),
        'rm -- '+shlex.quote(remote)])
    run(['ssh',*options,host,command])
    # Health is checked over the same authenticated SSH transport.
    run(['ssh',*options,host,'python3 -c '+shlex.quote("import json,time,urllib.request; time.sleep(2); r=json.load(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5)); assert r['mode']=='standalone-web'; print('VM health verified')")])
    d.checkpoint('vm_release',digest);d.checkpoint('vm_ssh_deployed',True)
    print('Release installed and checked over SSH:',digest[:16],flush=True)


def gateway(cutover=False):
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
    args=parser.parse_args()
    try:
        if args.action=='publish':publish(args.ssh_interface)
        else:gateway(args.action=='cutover')
    except Exception as exc:
        print('VM release stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)
        raise SystemExit(1)
