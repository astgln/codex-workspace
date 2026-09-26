"""Bounded ciphertext relay. No private keys, decryption, or execution authority."""
import base64
import hashlib
import json
import re
import time

MAX_CIPHERTEXT = 68000
MAX_STORAGE = 100 * 1024 * 1024
MAX_RECORDS = 100000
KINDS = frozenset(('request', 'response', 'history', 'catalog', 'push', 'key-wrap', 'control', 'control-result'))
FIELDS = frozenset(('v', 'context', 'key_id', 'signer', 'salt', 'nonce', 'ciphertext', 'signature'))


class Invalid(ValueError):
    pass


class CapacityExceeded(ValueError):
    """Storage is full; retrying a different revision cannot resolve it."""


class Conflict(ValueError):
    pass


def _binary(value, maximum, exact=None):
    if (not isinstance(value, str) or len(value) > (maximum * 4 + 2) // 3
            or not re.fullmatch('[A-Za-z0-9_-]*', value)):
        raise Invalid('Invalid opaque record')
    try:
        raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except ValueError:
        raise Invalid('Invalid opaque record') from None
    if (len(raw) > maximum or exact is not None and len(raw) != exact
            or base64.urlsafe_b64encode(raw).decode().rstrip('=') != value):
        raise Invalid('Invalid opaque record')
    return raw


def validate(envelope):
    if (not isinstance(envelope, dict) or set(envelope) != FIELDS
            or type(envelope['v']) is not int or envelope['v'] != 1):
        raise Invalid('Only versioned ciphertext envelopes are accepted')
    context = envelope['context']
    if not isinstance(context, list) or len(context) != 5:
        raise Invalid('Invalid opaque context')
    try:
        strings = all(isinstance(s, str) and 0 < len(s.encode('utf-8')) <= 512 for s in context[:4])
    except UnicodeError:
        strings = False
    if (not strings or context[2] not in KINDS or type(context[4]) is not int
            or not 1 <= context[4] <= 9007199254740991):
        raise Invalid('Invalid opaque context')
    for field in ('key_id', 'signer', 'salt'):
        _binary(envelope[field], 32, 32)
    _binary(envelope['nonce'], 12, 12)
    _binary(envelope['signature'], 64, 64)
    if len(_binary(envelope['ciphertext'], MAX_CIPHERTEXT)) < 16:
        raise Invalid('Invalid opaque ciphertext')
    if context[2] in ('request','control'):
        _binary(context[3], 32, 32)
        if context[4] != 1:
            raise Invalid('Encrypted requests are immutable')
    return context


def _initialize(db):
    # Auxiliary tables follow history/push storage: included in SQLite backups,
    # independent of the old domain-state serializer and its plaintext columns.
    db.execute('''CREATE TABLE IF NOT EXISTS opaque_records (
      workspace TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL, record TEXT NOT NULL,
      revision INTEGER NOT NULL, sequence INTEGER NOT NULL UNIQUE, envelope TEXT NOT NULL,
      digest TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY(workspace,scope,kind,record))''')
    db.execute('CREATE TABLE IF NOT EXISTS opaque_sequence (id INTEGER PRIMARY KEY CHECK(id=1), value INTEGER NOT NULL)')
    db.execute('INSERT OR IGNORE INTO opaque_sequence VALUES(1,0)')


def publish(store, body, *, browser=False):
    if not isinstance(body, dict) or set(body) != {'envelope'}:
        raise Invalid('Only an encrypted envelope is accepted')
    envelope = body['envelope']
    workspace, scope, kind, record, revision = validate(envelope)
    if (browser and kind not in ('request','control')) or (not browser and kind in ('request','control')):
        raise Invalid('Invalid encrypted publication direction')
    encoded = json.dumps(envelope, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    db = store.connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        _initialize(db)
        existing = db.execute('SELECT revision,sequence,digest,length(envelope) FROM opaque_records WHERE workspace=? AND scope=? AND kind=? AND record=?',
                              (workspace, scope, kind, record)).fetchone()
        if existing and revision <= existing[0]:
            if revision == existing[0] and digest == existing[2]:
                db.commit()
                return {'sequence': existing[1], 'duplicate': True}
            raise Conflict('Encrypted revision conflict')
        count, total = db.execute('SELECT count(*),coalesce(sum(length(envelope)),0) FROM opaque_records').fetchone()
        if (not existing and count >= MAX_RECORDS) or total - (existing[3] if existing else 0) + len(encoded) > MAX_STORAGE:
            raise CapacityExceeded('Encrypted storage quota exceeded')
        db.execute('UPDATE opaque_sequence SET value=value+1 WHERE id=1')
        sequence = db.execute('SELECT value FROM opaque_sequence WHERE id=1').fetchone()[0]
        db.execute('''INSERT INTO opaque_records VALUES(?,?,?,?,?,?,?,?,?)
          ON CONFLICT(workspace,scope,kind,record) DO UPDATE SET revision=excluded.revision,
          sequence=excluded.sequence,envelope=excluded.envelope,digest=excluded.digest,created=excluded.created''',
          (workspace, scope, kind, record, revision, sequence, encoded, digest, int(time.time())))
        db.commit()
        return {'sequence': sequence, 'duplicate': False}
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def read(store, body, *, browser=False):
    if not isinstance(body, dict) or set(body) != {'workspace', 'scope', 'kind', 'after'}:
        raise Invalid('Invalid encrypted read')
    workspace, scope, kind, after = (body[k] for k in ('workspace', 'scope', 'kind', 'after'))
    try:
        valid = all(isinstance(s, str) and 0 < len(s.encode('utf-8')) <= 512 for s in (workspace, scope))
    except UnicodeError:
        valid = False
    if (not valid or not isinstance(kind, str) or kind not in KINDS or type(after) is not int or not 0 <= after <= 9007199254740991
            or not browser and kind not in ('request','control')):
        raise Invalid('Invalid encrypted read')
    db = store.connect()
    try:
        # Initialization may write; acquire the writer reservation before reads
        # to avoid SQLITE_BUSY on deferred read-to-write upgrades.
        db.execute('BEGIN IMMEDIATE')
        _initialize(db)
        rows = db.execute('''SELECT sequence,envelope FROM opaque_records WHERE workspace=? AND scope=? AND kind=?
                            AND sequence>? ORDER BY sequence LIMIT 51''', (workspace, scope, kind, after)).fetchall()
        entries, size, cursor = [], 0, after
        for sequence, encoded in rows:
            if len(entries) >= 50 or entries and size + len(encoded) > 256000:
                break
            entries.append({'sequence': sequence, 'envelope': json.loads(encoded)})
            size += len(encoded); cursor = sequence
        db.commit()
        return {'records': entries, 'after': cursor, 'more': len(rows) > len(entries)}
    finally:
        db.close()


def publish_batch(store,body):
    if not isinstance(body,dict) or set(body)!={'envelopes'} or not isinstance(body['envelopes'],list) or not 1<=len(body['envelopes'])<=50:
        raise Invalid('Invalid encrypted batch')
    for envelope in body['envelopes']:
        if validate(envelope)[2] in ('request','control'):raise Invalid('Invalid publication direction')
    # Each immutable record is independently durable. A partial network failure
    # retries the same ciphertext; existing records return duplicate receipts.
    return {'results':[publish(store,{'envelope':e}) for e in body['envelopes']]}
