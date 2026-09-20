"""Cryptographic checks use ephemeral test keys, never real Telegram tokens."""
import json
import hashlib
import hmac
import unittest
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cloud import login, workspace, runtime


class LoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.key.public_key()))
        cls.jwk.update(kid='test-key', use='sig', alg='RS256')

    def token(self, **changes):
        claims = dict(iss=login.ISSUER, aud='123', sub='different-subject', id=42,
                      iat=1000, exp=2000, nonce='nonce', preferred_username='Owner')
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm='RS256', headers={'kid': 'test-key'})

    def verify(self, token):
        return login.verify_id_token(token, '123', 'nonce', 1001, [self.jwk])

    def test_verified_numeric_id_not_subject(self):
        self.assertEqual(self.verify(self.token()), {'id': 42, 'username': 'owner'})

    def test_invalid_claims(self):
        for changes in [dict(aud='another'), dict(iss='https://example.com'),
                        dict(nonce='other'), dict(exp=1001), dict(iat=600),
                        dict(iat=1040), dict(id=True), dict(id='42'), dict(id=-1)]:
            with self.subTest(changes=changes), self.assertRaises(workspace.Unauthorized):
                self.verify(self.token(**changes))

    def test_signature_algorithm_and_unknown_key(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        claims = jwt.decode(self.token(), options={'verify_signature': False})
        bad = [jwt.encode(claims, other, algorithm='RS256', headers={'kid':'test-key'}),
               jwt.encode(claims, 'test-only-secret', algorithm='HS256', headers={'kid':'test-key'}),
               jwt.encode(claims, self.key, algorithm='RS256', headers={'kid':'unknown'}),
               'malformed']
        for token in bad:
            with self.assertRaises(workspace.Unauthorized): self.verify(token)

    def test_unknown_critical_jwt_extension_is_rejected(self):
        claims=jwt.decode(self.token(), options={'verify_signature':False})
        token=jwt.encode(claims,self.key,algorithm='RS256',headers={
            'kid':'test-key','crit':['unsupported-policy'],'unsupported-policy':True})
        with self.assertRaises(workspace.Unauthorized):self.verify(token)

    def test_challenge_expiry_tampering_and_one_use(self):
        challenge = login.new_challenge('test-secret', 1000)
        self.assertEqual(login.verify_challenge(challenge['challenge'], 'test-secret', 1001), challenge['nonce'])
        for value, now in [(challenge['challenge'], 1300), (challenge['challenge']+'x',1001)]:
            with self.assertRaises(workspace.Unauthorized): login.verify_challenge(value,'test-secret',now)
        state = {}
        login.consume_challenge(state, challenge['nonce'], 1001)
        with self.assertRaises(workspace.Unauthorized): login.consume_challenge(state, challenge['nonce'],1002)

    def test_session_tamper_and_expiry(self):
        token = workspace.issue_session(42, 'test-secret', 1000)
        self.assertEqual(workspace.verify_session(token,'test-secret',1001),42)
        for value, secret, now in [(token+'x','test-secret',1001),(token,'other',1001),
                                   (token,'test-secret',1000+workspace.SESSION_TTL)]:
            with self.assertRaises(workspace.Unauthorized): workspace.verify_session(value,secret,now)

    def test_browser_session_cannot_authenticate_collector(self):
        token = workspace.issue_session(42, 'test-secret', 1000)
        with patch.dict('os.environ', {'CLIENT_KEY_HASH':'not-this-token'}):
            self.assertFalse(runtime.authorized({'headers':{'Authorization':'Workspace '+token}}))

    def test_public_key_cache_expiry_and_private_keys_rejected(self):
        state = {}
        login.cache_keys(state, {'keys':[self.jwk], 'fetched_at':1000}, 1001)
        keys = login.cached_keys(state,1002)
        self.assertEqual(login.verify_id_token(self.token(),'123','nonce',1002,keys),{'id':42,'username':'owner'})
        self.assertIsNone(login.cached_keys(state,1000+login.CACHE_TTL))
        for body in ({'keys':[{**self.jwk,'d':'private'}],'fetched_at':1000},
                     {'keys':[self.jwk],'fetched_at':2000}, {'keys':[],'fetched_at':1000}):
            with self.assertRaises(ValueError): login.cache_keys({},body,1001)


class WidgetLoginTests(unittest.TestCase):
    def signed(self, secret='123:test-secret', **changes):
        data=dict(id=42,first_name='Test',last_name='User',username='Owner',auth_date=1000,photo_url='https://example.test/photo')
        data.update(changes)
        canonical='\n'.join(f'{k}={v}' for k,v in sorted(data.items()))
        data['hash']=hmac.new(hashlib.sha256(secret.encode()).digest(),canonical.encode(),hashlib.sha256).hexdigest()
        return data

    def test_signed_widget_and_every_profile_field_checked(self):
        data=self.signed()
        self.assertEqual(login.verify_widget(data,'123:test-secret',1001),{'id':42,'username':'owner'})
        for field,value in [('id',99),('username','attacker'),('first_name','changed'),('photo_url','https://evil.test'),('hash','0'*64)]:
            with self.subTest(field=field),self.assertRaises(workspace.Unauthorized):
                login.verify_widget({**data,field:value},'123:test-secret',1001)
        with self.assertRaises(workspace.Unauthorized):login.verify_widget(data,'different-bot',1001)

    def test_widget_expiry_types_and_ambiguous_fields_rejected(self):
        for changes in [dict(auth_date=600),dict(auth_date=1100),dict(id=True),dict(id=0),dict(first_name='line\nusername=owner'),dict(username={'name':'owner'}),dict(extra='unsigned')]:
            with self.subTest(changes=changes),self.assertRaises(workspace.Unauthorized):
                login.verify_widget(self.signed(**changes),'123:test-secret',1001)
        with self.assertRaises(workspace.Unauthorized):login.verify_widget(None,'123:test-secret',1001)

    def test_proof_cannot_be_reused_with_new_challenge(self):
        state={};data=self.signed()
        login.consume_widget(state,data['hash'],1001)
        self.assertNotIn(data['hash'],state['login_widget_proofs'])
        with self.assertRaises(workspace.Unauthorized):login.consume_widget(state,data['hash'],1002)


if __name__ == '__main__': unittest.main()
