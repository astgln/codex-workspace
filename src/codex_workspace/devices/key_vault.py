"""Private local authority and scope keys; ciphertext-only recovery exports."""
import json
import os
from pathlib import Path
import secrets
import sqlite3

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from codex_workspace.crypto.key_material import key_entries, origin, private_key, public_key, read_object, validate_bundle
from codex_workspace.crypto.workspace_crypto import Context, CryptoError, decode, encode, key_id, open_envelope, public_bytes, recovery_key, seal, signer_id


def _private_path(path: Path, *, create=False):
    parent = path.parent.stat()
    if path.parent.is_symlink() or parent.st_mode & 0o077 or parent.st_uid != os.getuid():
        raise CryptoError('Keys require a private local directory')
    if create:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except FileExistsError:
            raise CryptoError('Key vault already exists; refusing to replace it') from None
    if path.is_symlink() or not path.is_file():
        raise CryptoError('Key vault is unavailable')
    info = path.stat()
    if info.st_mode & 0o077 or info.st_uid != os.getuid() or info.st_nlink != 1:
        raise CryptoError('Unsafe key vault permissions')


class KeyVault:
    @classmethod
    def create(cls, path: Path, public_origin: str):
        path = path.absolute()
        origin(public_origin)
        _private_path(path, create=True)
        authority = ec.generate_private_key(ec.SECP256R1())
        encoded = encode(authority.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
        cls._initialize(path, encode(secrets.token_bytes(32)), public_origin, encoded, 1, [])
        return cls(path)

    @staticmethod
    def _initialize(path, workspace, public_origin, authority, revision, keys):
        db = sqlite3.connect(path)
        try:
            db.executescript("""
              CREATE TABLE identity (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
                workspace TEXT NOT NULL, origin TEXT NOT NULL, authority TEXT NOT NULL, revision INTEGER NOT NULL);
              CREATE TABLE scope_keys (scope TEXT NOT NULL, epoch INTEGER NOT NULL, key BLOB NOT NULL,
                PRIMARY KEY(scope,epoch));
            """)
            db.execute('INSERT INTO identity VALUES(1,1,?,?,?,?)', (workspace,public_origin,authority,revision))
            db.executemany('INSERT INTO scope_keys VALUES(?,?,?)',
                           [(k['scope'],k['epoch'],decode(k['key'],maximum=32,exact=32)) for k in keys])
            db.commit()
        finally:
            db.close()

    @classmethod
    def restore(cls, path: Path, packet: dict, code: str, *, expected_origin: str, minimum_revision=1):
        recovered = read_recovery(packet,code,expected_origin=expected_origin,minimum_revision=minimum_revision)
        keys = list(recovered['keys'])
        latest = {}
        for entry in keys:
            latest[entry['scope']] = max(latest.get(entry['scope'],0),entry['epoch'])
        for scope, epoch in sorted(latest.items()):
            raw=secrets.token_bytes(32)
            keys.append({'scope':scope,'epoch':epoch+1,'key':encode(raw),'id':key_id(raw)})
        key_entries(keys)
        revision=recovered['revision']+1
        Context(recovered['workspace'],'recovery','key-wrap','restore',revision).wire()
        path=path.absolute()
        _private_path(path,create=True)
        cls._initialize(path,recovered['workspace'],expected_origin,recovered['authority_private'],revision,keys)
        # No device registry or execution receipts are imported from a server.
        # New request keys prevent old ciphertext commands from being replayed.
        return cls(path)

    def __init__(self, path: Path):
        path = path.absolute()
        _private_path(path)
        self.db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA secure_delete=ON')
        try:
            row = self.db.execute('SELECT * FROM identity WHERE id=1').fetchone()
            if row is None or row['version'] != 1:
                raise CryptoError('Unsupported key vault')
            decode(row['workspace'], maximum=32, exact=32)
            self.origin = origin(row['origin'])
            self.workspace = row['workspace']
            self.authority = private_key(row['authority'])
        except Exception:
            self.db.close()
            raise CryptoError('Key vault cannot be opened') from None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def scope_key(self, scope: str, *, rotate=False):
        Context(self.workspace, scope, 'key-wrap', 'scope', 1).wire()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM scope_keys WHERE scope=? ORDER BY epoch DESC LIMIT 1', (scope,)).fetchone()
            if row is None or rotate:
                epoch, raw = (row['epoch'] + 1 if row else 1), secrets.token_bytes(32)
                Context(self.workspace, scope, 'key-wrap', 'scope', epoch).wire()
                self.db.execute('INSERT INTO scope_keys VALUES(?,?,?)', (scope, epoch, raw))
                self.db.execute('UPDATE identity SET revision=revision+1 WHERE id=1')
            else:
                epoch, raw = row['epoch'], row['key']
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return {'scope': scope, 'epoch': epoch, 'key': encode(raw), 'id': key_id(raw)}

    def assert_ready(self):
        for name in ('key_transition','acl_transition'):
            table=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()
            if table and self.db.execute('SELECT 1 FROM '+name).fetchone():
                raise CryptoError('Interrupted key transition requires local reconciliation')

    def active_key(self, scope: str):
        """Requests must use the current epoch, never a relay-selected old key."""
        self.assert_ready()
        row = self.db.execute('SELECT * FROM scope_keys WHERE scope=? ORDER BY epoch DESC LIMIT 1', (scope,)).fetchone()
        if row is None:
            raise CryptoError('Scope is not configured locally')
        return {'scope': scope, 'epoch': row['epoch'], 'key': encode(row['key']), 'id': key_id(row['key'])}

    def _snapshot(self):
        # One consistent transaction: rotation cannot race the exported revision.
        self.db.execute('BEGIN')
        try:
            identity = dict(self.db.execute('SELECT * FROM identity WHERE id=1').fetchone())
            keys = [{'scope': r['scope'], 'epoch': r['epoch'], 'key': encode(r['key']), 'id': key_id(r['key'])}
                    for r in self.db.execute('SELECT * FROM scope_keys ORDER BY scope,epoch')]
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        key_entries(keys)
        return identity, keys

    def bundle(self, device_public: bytes, scopes: set[str]) -> bytes:
        """Explicit local selection; never accept scope lists from a relay response."""
        self.assert_ready()
        device = signer_id(public_key(encode(device_public)))
        if not isinstance(scopes, set) or any(not isinstance(s, str) for s in scopes):
            raise CryptoError('Explicit local scope selection is required')
        identity, keys = self._snapshot()
        if not scopes.issubset({k['scope'] for k in keys}):
            raise CryptoError('Requested scope keys are not available locally')
        value = {'v': 1, 'workspace': self.workspace, 'origin': self.origin, 'device': device,
                 'authority': encode(public_bytes(self.authority)), 'revision': identity['revision'],
                 'keys': [k for k in keys if k['scope'] in scopes]}
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        validate_bundle(raw, workspace=self.workspace, expected_origin=self.origin,
                        device=device, authority=public_bytes(self.authority))
        return raw

    def export_recovery(self, code: str) -> dict:
        identity, keys = self._snapshot()
        value = {'v': 1, 'workspace': self.workspace, 'origin': self.origin,
                 'authority_private': identity['authority'], 'revision': identity['revision'], 'keys': keys}
        context = Context(self.workspace, 'recovery', 'key-wrap', 'authority-backup', identity['revision'])
        return {'v': 1, 'workspace': self.workspace, 'authority': encode(public_bytes(self.authority)),
                'revision': identity['revision'], 'envelope': seal(recovery_key(code), self.authority, context,
                    json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())}


def read_recovery(packet: dict, code: str, *, expected_origin: str, minimum_revision=1):
    """Recovery code authenticates a first restore; a known revision rejects rollback."""
    if (not isinstance(packet, dict) or set(packet) != {'v', 'workspace', 'authority', 'revision', 'envelope'}
            or type(packet['v']) is not int or packet['v'] != 1 or type(packet['revision']) is not int
            or packet['revision'] < minimum_revision):
        raise CryptoError('Invalid or outdated recovery package')
    decode(packet['workspace'], maximum=32, exact=32)
    authority = public_key(packet['authority'])
    context = Context(packet['workspace'], 'recovery', 'key-wrap', 'authority-backup', packet['revision'])
    value = read_object(open_envelope(recovery_key(code), authority, context, packet['envelope']))
    if (set(value) != {'v', 'workspace', 'origin', 'authority_private', 'revision', 'keys'}
            or type(value['v']) is not int or value['v'] != 1 or value['workspace'] != packet['workspace']
            or type(value['revision']) is not int or value['revision'] != packet['revision']
            or value['origin'] != origin(expected_origin)
            or public_bytes(private_key(value['authority_private'])) != public_bytes(authority)):
        raise CryptoError('Invalid recovery package identity')
    key_entries(value['keys'])
    return value
