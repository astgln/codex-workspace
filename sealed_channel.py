"""Opt-in endpoint transport over the opaque relay; no plaintext fallback."""
import hashlib
import json

from workspace_crypto import Context, CryptoError, decode, seal


class SealedChannel:
    def __init__(self, api, vault):
        if api.url != vault.origin:
            raise CryptoError('Encrypted endpoint does not match the pinned origin')
        self.api, self.vault = api, vault
        vault.db.execute('''CREATE TABLE IF NOT EXISTS encrypted_outbox (
          scope TEXT NOT NULL, kind TEXT NOT NULL, record TEXT NOT NULL, revision INTEGER NOT NULL,
          digest TEXT NOT NULL, envelope TEXT NOT NULL, PRIMARY KEY(scope,kind,record,revision))''')

    def publish(self, scope: str, kind: str, record: str, revision: int, payload: dict):
        if kind not in ('history', 'response', 'catalog', 'push', 'key-wrap', 'control-result') or not isinstance(payload, dict):
            raise CryptoError('Invalid encrypted publication')
        context = Context(self.vault.workspace, scope, kind, record, revision)
        context.wire()
        # The caller supplies already filtered public content, never raw tool output.
        try:
            plaintext = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        except (ValueError, UnicodeError, TypeError, RecursionError):
            raise CryptoError('Invalid encrypted publication') from None
        if len(plaintext) > 67984:
            raise CryptoError('Encrypted publication must be split into bounded records')
        digest = hashlib.sha256(plaintext).hexdigest()
        db = self.vault.db
        db.execute('BEGIN IMMEDIATE')
        try:
            row = db.execute('SELECT digest,envelope FROM encrypted_outbox WHERE scope=? AND kind=? AND record=? AND revision=?',
                             (scope, kind, record, revision)).fetchone()
            if row is not None:
                if row['digest'] != digest:
                    raise CryptoError('An encrypted revision cannot be changed')
                envelope = json.loads(row['envelope'])
            else:
                newest=db.execute('SELECT max(revision) FROM encrypted_outbox WHERE scope=? AND kind=? AND record=?',(scope,kind,record)).fetchone()[0]
                if newest is not None and revision<newest:
                    raise CryptoError('Encrypted publication was superseded locally')
                # Do not create scope keys from a request supplied by the relay.
                current = self.vault.active_key(scope)
                envelope = seal(decode(current['key'], maximum=32), self.vault.authority, context, plaintext)
                encoded = json.dumps(envelope, separators=(',', ':'))
                used = db.execute('SELECT coalesce(sum(length(envelope)),0) FROM encrypted_outbox').fetchone()[0]
                if used + len(encoded) > 100 * 1024 * 1024:
                    raise CryptoError('Encrypted outbox requires maintenance')
                db.execute('INSERT INTO encrypted_outbox VALUES(?,?,?,?,?,?)', (scope, kind, record, revision, digest, encoded))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        # Retrying an uncertain network result uses these exact persisted bytes.
        reply=self.api.call('/v2/e2ee/publish', {'envelope': envelope})
        if isinstance(reply,dict) and type(reply.get('sequence')) is int and reply['sequence']>0 and type(reply.get('duplicate')) is bool:
            # Keep the newest ciphertext for uncertain retries, but not every
            # historical heartbeat and streaming progress revision forever.
            db.execute('DELETE FROM encrypted_outbox WHERE scope=? AND kind=? AND record=? AND revision<?',(scope,kind,record,revision))
        return reply

    def snapshot(self, scope, kind, record, payload):
        """Allocate a stable local revision; retries retain the same ciphertext."""
        encoded=json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        digest=hashlib.sha256(encoded.encode()).hexdigest()
        db=self.vault.db
        db.execute('CREATE TABLE IF NOT EXISTS encrypted_snapshots (scope TEXT,kind TEXT,record TEXT,digest TEXT,revision INTEGER,PRIMARY KEY(scope,kind,record))')
        db.execute('BEGIN IMMEDIATE')
        try:
            row=db.execute('SELECT digest,revision FROM encrypted_snapshots WHERE scope=? AND kind=? AND record=?',(scope,kind,record)).fetchone()
            revision=1 if row is None else row['revision']+(row['digest']!=digest)
            db.execute('INSERT INTO encrypted_snapshots VALUES(?,?,?,?,?) ON CONFLICT(scope,kind,record) DO UPDATE SET digest=excluded.digest,revision=excluded.revision',(scope,kind,record,digest,revision))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK');raise
        return self.publish(scope,kind,record,revision,payload)

    def requests(self, scope: str, after: int, *, kind='request'):
        if kind not in ('request','control'):raise CryptoError('Invalid intake kind')
        self.vault.active_key(scope)  # Must already belong to the local catalog/key set.
        result = self.api.call('/v2/e2ee/read', {'workspace': self.vault.workspace,
                              'scope': scope, 'kind': kind, 'after': after})
        if (not isinstance(result, dict) or set(result) != {'records', 'after', 'more'}
                or not isinstance(result['records'], list) or len(result['records']) > 50
                or type(result['after']) is not int or type(result['more']) is not bool):
            raise CryptoError('Invalid encrypted relay response')
        cursor = after
        for entry in result['records']:
            if (not isinstance(entry, dict) or set(entry) != {'sequence', 'envelope'}
                    or type(entry['sequence']) is not int or not cursor < entry['sequence'] <= 9007199254740991
                    or not isinstance(entry['envelope'], dict)):
                raise CryptoError('Invalid encrypted relay record')
            cursor = entry['sequence']
            context = entry['envelope'].get('context')
            if (not isinstance(context, list) or len(context) != 5 or
                    context[:3] != [self.vault.workspace, scope, kind] or type(context[4]) is not int or context[4] != 1):
                raise CryptoError('Encrypted relay context changed')
        if result['after'] != cursor or not result['records'] and result['more']:
            raise CryptoError('Invalid encrypted relay cursor')
        return result

    def accept(self, trust, scope: str, entry: dict, *, now=None):
        """Verify locally before handing a request to the execution queue.

        This interface alone does not execute or automatically retry commands.
        Queue integration must commit its durable intent in the same transaction.
        """
        current = self.vault.active_key(scope)
        envelope = entry['envelope']
        context = envelope.get('context')
        if not isinstance(context, list) or len(context) != 5:
            raise CryptoError('Invalid encrypted request')
        expected = Context(self.vault.workspace, scope, 'request', context[3], 1)
        return trust.accept_request(decode(current['key'], maximum=32), expected, envelope, now=now)
