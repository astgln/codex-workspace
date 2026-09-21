"""Local trust and replay records. Never instantiate this store on the relay.

Pairing invitations are bearer capabilities delivered outside the relay (QR or
URL fragment). Only the local endpoint can create them or enroll/revoke keys.
Runtime transport integration must not expose these management methods as RPCs.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import UnsupportedAlgorithm
from request_intent import validate_request
from key_material import validate_bundle

from workspace_crypto import (Context, CryptoError, decode, encode, open_envelope,
                              public_bytes, seal, signer_id)

PAIRING_PROOF = b'codex-workspace/device-pairing/v1'
PAIRING_LIFETIME = 600


class ReplayError(CryptoError):
    pass


def _public(raw):
    if not isinstance(raw, bytes) or len(raw) > 256:
        raise CryptoError('Invalid device key')
    try:
        key = serialization.load_der_public_key(raw)
        if public_bytes(key) != raw:
            raise CryptoError('Invalid device key')
        return key
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise CryptoError('Invalid device key') from None


class TrustStore:
    def __init__(self, path: Path, workspace: str):
        Context(workspace, 'devices', 'key-wrap', 'validation', 1).wire()
        # Parent must already be a private local directory. No implicit mkdir
        # through symlinks and no permissions changes to a caller's directory.
        if path.parent.stat().st_mode & 0o077 or path.parent.is_symlink():
            raise CryptoError('Device store requires a private directory')
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
                raise CryptoError('Unsafe device store permissions') from None
        else:
            os.close(fd)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=DELETE;
          PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), workspace TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, public_key BLOB NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS accepted_requests (record TEXT PRIMARY KEY, scope TEXT NOT NULL, signer TEXT NOT NULL, accepted INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS pairings (id TEXT PRIMARY KEY, secret BLOB, expires INTEGER NOT NULL, authority TEXT NOT NULL,
            offer_hash TEXT, response TEXT);
        ''')
        self.db.execute('INSERT OR IGNORE INTO identity VALUES(1,?)', (workspace,))
        if self.db.execute('SELECT workspace FROM identity').fetchone()[0] != workspace:
            self.db.close()
            raise CryptoError('Device store belongs to another workspace')
        self.workspace = workspace

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def trust_device(self, public_key: bytes):
        """Local administrative operation, never based on a relay assertion."""
        ident = signer_id(_public(public_key))
        self.db.execute('INSERT OR IGNORE INTO devices(id,public_key) VALUES(?,?)', (ident, public_key))
        if self.db.execute('SELECT revoked FROM devices WHERE id=?', (ident,)).fetchone()[0]:
            # A revoked key must not be resurrected by replaying a pairing.
            raise CryptoError('Device key was revoked; generate a new key')
        return ident

    def revoke_device(self, ident: str):
        self.db.execute('UPDATE devices SET revoked=1 WHERE id=?', (ident,))

    def accept_request(self, key: bytes, expected: Context, envelope: dict, *, now=None, persist=None) -> dict:
        """Authenticate and consume a client nonce atomically, before execution.

        Transport redelivery cannot create a second execution even if it supplies
        a new relay ID, task, ciphertext or device signature. A consumed nonce is
        not rolled back after a crash; callers must use durable execution receipts
        to recover the original operation rather than create a fresh request.
        """
        if expected.workspace != self.workspace or expected.kind != 'request' or expected.revision != 1:
            raise CryptoError('Invalid request context')
        expected.wire()
        # Client nonces are exactly 256 random bits, encoded canonically.
        decode(expected.record, maximum=32, exact=32)
        if not isinstance(envelope, dict) or not isinstance(envelope.get('signer'), str):
            raise CryptoError('Untrusted device')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM devices WHERE id=?', (envelope['signer'],)).fetchone()
            if row is None or row['revoked']:
                raise CryptoError('Untrusted device')
            content = open_envelope(key, _public(row['public_key']), expected, envelope)
            received = int(time.time() if now is None else now)
            request = validate_request(content, expected, received)
            if self.db.execute('SELECT 1 FROM accepted_requests WHERE record=?', (expected.record,)).fetchone():
                raise ReplayError('Encrypted request already accepted; do not execute again')
            self.db.execute('INSERT INTO accepted_requests VALUES(?,?,?,?)',
                            (expected.record, expected.scope, envelope['signer'], received))
            if persist is not None:
                # Persist the execution intent using this same connection. No
                # network or CLI operations may run in this callback.
                persist(self.db, request)
            self.db.execute('COMMIT')
            return request
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def invite(self, authority_public: bytes, *, now=None) -> dict:
        """Secret result is for the trusted UI/QR only; never send it to a server."""
        _public(authority_public)
        now = int(time.time() if now is None else now)
        ident, secret = encode(secrets.token_bytes(32)), secrets.token_bytes(32)
        self.db.execute('DELETE FROM pairings WHERE expires<=?', (now,))
        self.db.execute('INSERT INTO pairings(id,secret,expires,authority) VALUES(?,?,?,?)',
                        (ident, secret, now + PAIRING_LIFETIME, signer_id(_public(authority_public))))
        return {'v': 1, 'workspace': self.workspace, 'id': ident, 'secret': encode(secret),
                'authority': encode(authority_public), 'expires': now + PAIRING_LIFETIME}

    def pair(self, invitation: str, device_public: bytes, offer: dict, authority_signing,
             key_bundle: bytes, *, expected_origin: str, now=None) -> dict:
        """Consume one invitation, authorize one key, return a signed key bundle.

        The key bundle must contain only the locally chosen keys for this device.
        The relay cannot select its contents. Retries of the exact same offer
        return the same ciphertext; another device cannot consume it again.
        """
        now = int(time.time() if now is None else now)
        device = _public(device_public)
        if not isinstance(offer, dict):
            raise CryptoError('Invalid pairing offer')
        # Hash canonical JSON only for local retry identity, not as a signature format.
        try:
            serialized = json.dumps(offer, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        except (ValueError, TypeError, RecursionError):
            raise CryptoError('Invalid pairing offer') from None
        if len(serialized) > 8192:
            raise CryptoError('Invalid pairing offer')
        digest = hashlib.sha256(device_public + serialized).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM pairings WHERE id=?', (invitation,)).fetchone()
            if row is None or row['expires'] <= now:
                raise CryptoError('Pairing invitation expired or unavailable')
            if signer_id(authority_signing) != row['authority']:
                raise CryptoError('Pairing authority changed')
            if row['offer_hash'] is not None:
                if row['offer_hash'] != digest:
                    raise ReplayError('Pairing invitation already consumed')
                device_row = self.db.execute('SELECT revoked FROM devices WHERE id=?', (signer_id(device),)).fetchone()
                if device_row is None or device_row['revoked']:
                    raise CryptoError('Untrusted device')
                result = json.loads(row['response'])
            else:
                context = Context(self.workspace, 'devices', 'key-wrap', invitation, 1)
                if open_envelope(row['secret'], device, context, offer) != PAIRING_PROOF:
                    raise CryptoError('Invalid pairing offer')
                validate_bundle(key_bundle, workspace=self.workspace, expected_origin=expected_origin,
                                device=signer_id(device), authority=public_bytes(authority_signing))
                result = seal(row['secret'], authority_signing,
                              Context(self.workspace, 'devices', 'key-wrap', invitation, 2), key_bundle)
                self.trust_device(device_public)
                self.db.execute('UPDATE pairings SET secret=NULL,offer_hash=?,response=? WHERE id=?',
                                (digest, json.dumps(result), invitation))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
