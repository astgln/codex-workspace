#!/usr/bin/env python3
"""Provision the dedicated web VM; never alter unrelated machines."""
import argparse
import json
import subprocess
import ipaddress
from codex_workspace.ops.deploy import Deploy, STATE, ROOT, save


def provision(args):
    deployment = Deploy(args)
    key = STATE / 'web-vm-ed25519'
    if not key.exists():
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-C','codex-workspace-deploy','-f',str(key)],check=True)
    network = deployment.resource('vm_network',['vpc','network'],'codex-workspace')
    subnets = {}
    # General-access zones. Do not provision restricted preview zones merely
    # because the global zone listing advertises them as UP.
    zones = ['ru-central1-a','ru-central1-b','ru-central1-d','ru-central1-e']
    for index, zone in enumerate(zones):
        cidr = f'10.210.{index}.0/24'
        subnets[zone] = deployment.resource('vm_subnet_'+zone,['vpc','subnet'],'codex-workspace-'+zone,
            ['--network-id',network,'--zone',zone,'--range',cidr])
    # HTTPS and SSH can use different egress routes under split tunneling.
    source = str(ipaddress.IPv4Address(args.ssh_source))
    group = deployment.resource('vm_security',['vpc','security-group'],'codex-workspace',[
        '--network-id',network,
        '--rule','direction=ingress,port=22,protocol=tcp,v4-cidrs=['+source+'/32]',
        '--rule','direction=ingress,port=8080,protocol=tcp,v4-cidrs=[198.19.0.0/16]',
        '--rule','direction=egress,port=any,protocol=any,v4-cidrs=[0.0.0.0/0]'])
    deployment.checkpoint('vm_ssh_source',source)
    account = deployment.resource('vm_account',['iam','service-account'],'codex-workspace-vm')
    cloud_config = {'users':[{'name':'bridge','shell':'/bin/bash','lock_passwd':True,
        'sudo':'ALL=(ALL) NOPASSWD:ALL','ssh_authorized_keys':[key.with_suffix('.pub').read_text().strip()]}],
        'ssh_pwauth':False,'disable_root':True,'package_update':True,
        'packages':['python3-venv','unattended-upgrades'],
        'runcmd':[['systemctl','enable','--now','unattended-upgrades']]}
    config = STATE / 'vm-cloud-config.json'
    # JSON is valid YAML; cloud-init requires the leading content type marker.
    config.write_text('#cloud-config\n'+json.dumps(cloud_config))
    if args.recreate_empty and 'vm_instance' in deployment.state:
        if deployment.state.get('vm_app_installed'):
            raise RuntimeError('Refusing to recreate an initialized application VM')
        old=deployment.yc('compute','instance','get',deployment.state['vm_instance'])
        if old['name']!='codex-workspace' or old['service_account_id']!=account:
            raise RuntimeError('Refusing to replace an unrelated VM')
        deployment.yc('compute','instance','delete',old['id'])
        if not old['boot_disk'].get('auto_delete'):
            deployment.yc('compute','disk','delete',old['boot_disk']['disk_id'])
        del deployment.state['vm_instance']
        save(deployment.path,deployment.state)
    machine = deployment.resource('vm_instance',['compute','instance'],'codex-workspace',[
        '--zone','ru-central1-b','--platform','standard-v3','--cores','2','--core-fraction','20','--memory','2GB',
        '--create-boot-disk','image-family=ubuntu-2404-lts,image-folder-id=standard-images,size=20,type=network-ssd',
        '--network-interface','subnet-id='+subnets['ru-central1-b']+',nat-ip-version=ipv4,security-group-ids='+group,
        '--service-account-id',account,'--metadata-from-file','user-data='+str(config),
        '--metadata-options','aws-v1-http-endpoint=enabled,aws-v1-http-token=disabled,gce-http-endpoint=enabled,gce-http-token=enabled'])
    info = deployment.yc('compute','instance','get',machine)
    interface = info['network_interfaces'][0]['primary_v4_address']
    deployment.checkpoint('vm_private_ip',interface['address'])
    deployment.checkpoint('vm_public_ip',interface['one_to_one_nat']['address'])
    print('Dedicated web VM ready; SSH restricted to deployment source, HTTP to gateway network.',flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--folder',required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--owner',required=True)
    parser.add_argument('--ssh-source',required=True,help='Verified public IPv4 source for SSH; allowed as /32 only')
    parser.add_argument('--recreate-empty',action='store_true',help='Replace only this deployment’s uninitialized VM')
    try:
        provision(parser.parse_args())
    except Exception as exc:
        print('VM deployment stopped:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)
        raise SystemExit(1)
