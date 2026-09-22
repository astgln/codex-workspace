#!/usr/bin/env python3
"""Local key administration. Does not activate encryption or change live services.

Secrets are written only to explicit private files, never stdout or the relay.
"""
import argparse
import html
import json
import os
from pathlib import Path
import time

from device_keys import DeviceKeys
from device_trust import TrustStore
from key_vault import KeyVault
from pairing_channel import PairingChannel
from runtime_support import BridgeError, exclusive
from sealed_channel import SealedChannel
from workspace_client import API, STATE
from workspace_crypto import CryptoError, create_recovery_code


def write_private(path, content):
    path=Path(path).absolute()
    if path.parent.is_symlink() or path.parent.stat().st_mode&0o077 or path.parent.stat().st_uid!=os.getuid():
        raise CryptoError('Output requires a private directory owned by this user')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as out:
        out.write(content);out.flush();os.fsync(out.fileno())


def scopes_from_catalog(path):
    catalog=json.loads(Path(path).read_text())
    threads=catalog.get('threads')
    if not isinstance(threads,list):raise CryptoError('Invalid local catalog')
    scopes={'workspace'}
    for thread in threads:
        ident=thread.get('id')
        if not isinstance(ident,str) or not ident or ident=='workspace' or ident.startswith('device:'):
            raise CryptoError('Invalid local task scope')
        scopes.add(ident)
    return scopes


def backup(vault, package, code_file):
    # Refuse collisions before creating either output. Never overwrite an old
    # recovery artifact, especially one selected accidentally by a shell command.
    if package.exists() or package.is_symlink() or code_file.exists() or code_file.is_symlink() or package.absolute()==code_file.absolute():
        raise CryptoError('Recovery output already exists')
    code=create_recovery_code()
    packet=vault.export_recovery(code)
    write_private(code_file,code+'\n')
    write_private(package,json.dumps(packet,separators=(',',':'))+'\n')


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,default=STATE)
    sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--origin',required=True);init.add_argument('--catalog',type=Path,required=True)
    for name in ('init','backup'):
        cmd=init if name=='init' else sub.add_parser(name)
        cmd.add_argument('--package',type=Path,required=True);cmd.add_argument('--code-file',type=Path,required=True)
    invite=sub.add_parser('pair');invite.add_argument('--catalog',type=Path,required=True);invite.add_argument('--link-file',type=Path,required=True)
    revoke=sub.add_parser('revoke');revoke.add_argument('device')
    sub.add_parser('status');sub.add_parser('reconcile')
    restore=sub.add_parser('restore');restore.add_argument('--package',type=Path,required=True);restore.add_argument('--code-file',type=Path,required=True)
    restore.add_argument('--origin',required=True);restore.add_argument('--minimum-revision',type=int,required=True)
    args=parser.parse_args()
    try:
        lock=args.state/'e2ee-admin'
        lock.mkdir(mode=0o700,exist_ok=True)
        if lock.is_symlink() or lock.stat().st_mode&0o077 or lock.stat().st_uid!=os.getuid():
            raise CryptoError('Unsafe local administration directory')
        with exclusive(lock):
            path=args.state/'e2ee-keys.sqlite3'
            if args.command=='init':
                scopes=scopes_from_catalog(args.catalog)
                with KeyVault.create(path,args.origin) as vault:
                    for scope in scopes:vault.scope_key(scope)
                    backup(vault,args.package,args.code_file)
                print('Local keys and recovery package created. Live encryption remains unchanged.')
                return
            if args.command=='restore':
                if args.code_file.is_symlink() or args.code_file.stat().st_mode&0o077:raise CryptoError('Recovery code must be private')
                with KeyVault.restore(path,json.loads(args.package.read_text()),args.code_file.read_text().strip(),
                                      expected_origin=args.origin,minimum_revision=args.minimum_revision):pass
                print('Restored locally with rotated epochs. Devices must be paired again.')
                return
            with KeyVault(path) as vault:
                if args.command=='backup':
                    vault.assert_ready();backup(vault,args.package,args.code_file);print('Recovery package saved locally.');return
                with TrustStore(args.state/'web-queue.sqlite3',vault.workspace) as trust:
                    if args.command=='status':
                        devices=[{'id':row['id'],'revoked':bool(row['revoked'])} for row in trust.db.execute('SELECT id,revoked FROM devices')]
                        print(json.dumps({'workspace':vault.workspace,'devices':devices}));return
                    config=json.loads((args.state/'web.json').read_text())
                    api=API(config,state=args.state)
                    delivery=DeviceKeys(vault,trust,SealedChannel(api,vault))
                    if args.command=='reconcile':delivery.reconcile();print('Local transition reconciled.');return
                    if args.command=='revoke':delivery.revoke(args.device);delivery.publish();print('Device revoked; surviving devices received rotated keys.');return
                    scopes=scopes_from_catalog(args.catalog)
                    for scope in scopes:vault.scope_key(scope)
                    pairing=PairingChannel(api,vault,trust)
                    invitation,link=pairing.invite()
                    page='<!doctype html><meta name="referrer" content="no-referrer"><title>Pair device</title><p>Open on your trusted device within 10 minutes.</p><a rel="noreferrer" href="'+html.escape(link,quote=True)+'">Pair this device</a>'
                    write_private(args.link_file,page)
                    created=args.link_file.stat()
                    print('Private pairing page saved. Waiting for the device (up to 10 minutes).',flush=True)
                    try:
                        while time.time()<invitation['expires']:
                            if pairing.poll(invitation['id'],scopes):
                                delivery.publish();print('Device paired.');return
                            time.sleep(2)
                        raise CryptoError('Pairing expired')
                    finally:
                        # Only the file created exclusively by this invocation.
                        if args.link_file.exists() and not args.link_file.is_symlink():
                            current=args.link_file.stat()
                            if (current.st_dev,current.st_ino)==(created.st_dev,created.st_ino):args.link_file.unlink()
    except (CryptoError,BridgeError,OSError,ValueError,KeyError):
        raise SystemExit('E2EE administration failed; secrets and response details hidden.') from None


if __name__=='__main__':main()
