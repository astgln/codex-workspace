"""Explicit local pairing coordinator; never grants scopes chosen by the server."""
import json
from workspace_crypto import CryptoError, decode, encode, public_bytes


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
        grant = self.trust.pair(invitation_id, public, offer['envelope'], self.vault.authority,
                                self.vault.bundle(public, scopes), expected_origin=self.vault.origin)
        self.api.call('/v2/e2ee/pairing/grant', dict(body, envelope=grant))
        return True
