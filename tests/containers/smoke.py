"""Explicit HTTPS smoke check using ONLY a disposable setup-generated state."""
import argparse
import json
from pathlib import Path
import ssl
import httpx
from cryptography.hazmat.primitives.asymmetric import ec,utils
from codex_workspace.agent.workspace_client import API
from codex_workspace.agent.sealed_channel import SealedChannel
from codex_workspace.devices.key_vault import KeyVault
from codex_workspace.devices.device_trust import TrustStore
from codex_workspace.devices.pairing_channel import PairingChannel
from codex_workspace.devices.auth_registry import publish
from codex_workspace.crypto.device_auth import message,sign
from codex_workspace.crypto.workspace_crypto import Context,encode,decode,public_bytes,seal,open_envelope,signer_id


def check(state,ca,expect_existing=False):
    config=json.loads((state/'web.json').read_text());api=API(config,state=state)
    with httpx.Client(base_url=api.url,verify=ssl.create_default_context(cafile=str(ca)),trust_env=False) as browser, KeyVault(state/'e2ee-keys.sqlite3') as vault, TrustStore(state/'web-queue.sqlite3',vault.workspace) as trust:
        assert browser.get('/health').status_code==200
        home=browser.get('/');assert home.status_code==200 and '<html' in home.text
        assert browser.get('/sw.js').status_code==200
        assert browser.get('/auth/session').status_code==401
        browser.headers['Origin']=api.url
        def post(path,body):
            response=browser.post(path,json=body)
            assert response.status_code==200,(path,response.status_code)
            return response.json()
        pair=PairingChannel(api,vault,trust);invite,_=pair.invite()
        device=ec.generate_private_key(ec.SECP256R1());secret=decode(invite['secret'],maximum=32)
        offer=seal(secret,device,Context(vault.workspace,'devices','key-wrap',invite['id'],1),b'codex-workspace/device-pairing/v1')
        post('/auth/pairing/offer',{'workspace':vault.workspace,'id':invite['id'],'public_key':encode(public_bytes(device)),'envelope':offer})
        assert pair.poll(invite['id'],{'workspace'})
        wrapped=post('/auth/pairing/read',{'workspace':vault.workspace,'id':invite['id']})
        bundle=json.loads(open_envelope(secret,vault.authority.public_key(),Context(vault.workspace,'devices','key-wrap',invite['id'],2),wrapped['payload']['envelope']))
        publish(api,vault,trust)
        ident=signer_id(device);challenge=post('/auth/device/challenge',{'device':ident})
        der=decode(sign(device,message('login',api.url,vault.workspace,ident,challenge['nonce'],challenge['expires'])),maximum=80)
        a,b=utils.decode_dss_signature(der)
        post('/auth/device/session',{'device':ident,'nonce':challenge['nonce'],'signature':encode(a.to_bytes(32,'big')+b.to_bytes(32,'big'))})
        session=browser.get('/auth/session');assert session.status_code==200
        browser.headers['X-CSRF-Token']=session.json()['csrf']
        channel=SealedChannel(api,vault)
        receipt=channel.publish('workspace','catalog','docker-smoke',1,{'text':'DOCKER E2EE OK'})
        assert receipt['duplicate']==expect_existing, 'Persistent ciphertext did not survive recreation'
        result=post('/web/e2ee/read',{'workspace':vault.workspace,'scope':'workspace','kind':'catalog','after':0})
        assert 'DOCKER E2EE OK' not in json.dumps(result)
        envelope=next(row['envelope'] for row in result['records'] if row['envelope']['context'][3]=='docker-smoke')
        key=next(k for k in bundle['keys'] if k['scope']=='workspace')
        plain=open_envelope(decode(key['key'],maximum=32),vault.authority.public_key(),Context(vault.workspace,'workspace','catalog','docker-smoke',1),envelope)
        assert json.loads(plain)=={'text':'DOCKER E2EE OK'}
        assert browser.post('/web/e2ee/read',json={},headers={'Origin':'https://wrong.example'}).status_code==403
        print('HTTPS/static/pairing/device-login/CSRF/encrypted round trip verified; persisted record:',receipt['duplicate'])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable-state',type=Path,required=True)
    parser.add_argument('--ca',type=Path,required=True)
    parser.add_argument('--expect-existing',action='store_true')
    args=parser.parse_args();check(args.disposable_state,args.ca,args.expect_existing)
