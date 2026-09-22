"""Explicit local pairing coordinator; never grants scopes chosen by the server."""
import json
import hashlib
import time
from workspace_crypto import CryptoError, Context, decode, encode, public_bytes, open_envelope
from key_material import public_key


class PairingChannel:
    def __init__(self, api, vault, trust):
        if api.url != vault.origin or trust.workspace != vault.workspace:
            raise CryptoError('Pairing endpoint does not match local identity')
        self.api, self.vault, self.trust = api, vault, trust

    def invite(self):
        invitation = self.trust.invite(public_bytes(self.vault.authority))
        self.api.call('/v2/e2ee/pairing/register', {k: invitation[k] for k in ('workspace', 'id', 'expires')})
        # Caller presents this locally. Never log it or send it to the relay.
        fragment = encode(json.dumps(invitation, separators=(',', ':')).encode())
        return invitation, self.vault.origin + '/#pair=' + fragment

    def poll(self, invitation_id: str, scopes: set[str]):
        decode(invitation_id, maximum=32, exact=32)
        body = {'workspace': self.vault.workspace, 'id': invitation_id}
        result = self.api.call('/v2/e2ee/pairing/read', body)
        if not isinstance(result, dict) or set(result) != {'payload'}:
            raise CryptoError('Invalid pairing relay response')
        offer = result['payload']
        if offer is None:
            return False
        if not isinstance(offer, dict) or set(offer) != {'public_key', 'envelope'}:
            raise CryptoError('Invalid pairing offer')
        public = decode(offer['public_key'], maximum=256)
        # Authenticate possession before allocating any persistent device key.
        local=self.trust.db.execute('SELECT secret,expires,offer_hash FROM pairings WHERE id=?',(invitation_id,)).fetchone()
        if local is None or local['expires']<=int(time.time()):
            raise CryptoError('Pairing invitation expired')
        if local['secret'] is not None:
            proof=open_envelope(local['secret'],public_key(offer['public_key']),
                Context(self.vault.workspace,'devices','key-wrap',invitation_id,1),offer['envelope'])
            if proof!=b'codex-workspace/device-pairing/v1':raise CryptoError('Invalid pairing proof')
        else:
            serialized=json.dumps(offer['envelope'],sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
            if hashlib.sha256(public+serialized).hexdigest()!=local['offer_hash']:
                raise CryptoError('Pairing offer changed')
        from device_keys import delivery_scope, DeviceKeys
        from sealed_channel import SealedChannel
        from workspace_crypto import signer_id
        scope = delivery_scope(public)
        self.vault.scope_key(scope)
        grant = self.trust.pair(invitation_id, public, offer['envelope'], self.vault.authority,
                                self.vault.bundle(public, scopes | {scope}), expected_origin=self.vault.origin)
        DeviceKeys(self.vault,self.trust,SealedChannel(self.api,self.vault)).configure(signer_id(public_key(offer['public_key'])),scopes)
        self.api.call('/v2/e2ee/pairing/grant', dict(body, envelope=grant))
        return True
