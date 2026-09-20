"""Read only this service's Lockbox secret using the VM service account.

Run as root during deployment. Neither IAM credentials nor secret payloads are
printed or stored in cloud-init metadata, shell arguments, or application logs.
"""
import json
import os
from pathlib import Path
import sys
import urllib.request


def main():
    config=json.loads(Path(sys.argv[1]).read_text())
    opener=urllib.request.build_opener()
    request=urllib.request.Request('http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token',headers={'Metadata-Flavor':'Google'})
    with opener.open(request,timeout=10) as response:
        iam=json.load(response)['access_token']
    request=urllib.request.Request('https://payload.lockbox.api.cloud.yandex.net/lockbox/v1/secrets/'+config.pop('secret_id')+'/payload',headers={'Authorization':'Bearer '+iam})
    with opener.open(request,timeout=10) as response:
        entries=json.load(response)['entries']
    config['TELEGRAM_BOT_TOKEN']=next(e['textValue'] for e in entries if e['key']=='TELEGRAM_BOT_TOKEN')
    path=Path('/etc/codex-workspace/config.json')
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as output:json.dump(config,output)


if __name__=='__main__':
    try:main()
    except Exception:
        print('Service secret initialization failed; details hidden',file=sys.stderr)
        raise SystemExit(1)
