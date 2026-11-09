"""Encrypted operational backup identities. No credentials or network access.

Source attestations are signed by a separately controlled evidence principal;
backup manifests by the writer. Neither signature grants an export permission.
Only ciphertext is eligible for the existing Drive transport.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import re

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .drive_archive_transfer import canonical_json, decode_json

SCHEMA = 'drop-rate-operational-d1-encrypted-sqlite-v1'
SOURCE_SCHEMA = 'drop-rate-operational-d1-source-approval-v1'
DATABASE_NAME = 'drop-rate-d1-operational-shadow-20261106'
PREFIX = 'operational-d1-backups/v1'
MAX_CIPHERTEXT = 16_000_000  # Existing DR95 transport bound; do not raise implicitly.
SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9_.:-]{1,120}\Z')


class BackupGuard(ValueError):
    """Fixed aggregate error codes only; never include operational data."""


def need(ok, code):
    if not ok:
        raise BackupGuard(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def b64(data):
    return base64.b64encode(data).decode('ascii')


def unb64(value, size=None):
    try:
        need(isinstance(value, str), 'INVALID_BASE64')
        data = base64.b64decode(value, validate=True)
        need(size is None or len(data) == size, 'INVALID_KEY_OR_NONCE')
        return data
    except (ValueError, TypeError):
        raise BackupGuard('INVALID_BASE64') from None


def stamp(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        need(date.tzinfo is not None and date.utcoffset() is not None, 'INVALID_TIMESTAMP')
        return date.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise BackupGuard('INVALID_TIMESTAMP') from None


def signed(payload, private_key):
    return {'payload': payload, 'signature': b64(private_key.sign(canonical_json(payload)))}


def verified(record, public_key):
    need(isinstance(record, dict) and set(record) == {'payload', 'signature'}, 'INVALID_SIGNED_RECORD')
    need(isinstance(record['payload'], dict), 'INVALID_SIGNED_PAYLOAD')
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            unb64(record['signature'], 64), canonical_json(record['payload']))
    except Exception:
        raise BackupGuard('SIGNATURE_VERIFICATION_FAILED') from None
    return record['payload']


def source_approval(record, public_key):
    value = verified(record, public_key)
    need(set(value) == {'schema', 'database_name', 'database_id', 'generation_sha256',
         'generation_id', 'evidence_reference', 'evidence_sha256', 'schema_sha256',
         'table_fingerprints', 'approved_at'}, 'SOURCE_APPROVAL_FIELDS')
    need(value['schema'] == SOURCE_SCHEMA and value['database_name'] == DATABASE_NAME,
         'SOURCE_SCOPE_MISMATCH')
    need(isinstance(value['database_id'], str) and re.fullmatch(
        r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', value['database_id']),
         'SOURCE_DATABASE_ID_INVALID')
    for field in ('generation_sha256', 'evidence_sha256', 'schema_sha256'):
        need(isinstance(value[field], str) and SHA.fullmatch(value[field]), 'SOURCE_DIGEST_INVALID')
    need(value['generation_id'] == 'src-' + value['generation_sha256'][:32], 'SOURCE_GENERATION_INVALID')
    need(isinstance(value['evidence_reference'], str) and re.fullmatch(
        r'https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/[0-9]+',
        value['evidence_reference']), 'SOURCE_EVIDENCE_REFERENCE_INVALID')
    tables = value['table_fingerprints']
    need(isinstance(tables, dict) and 1 <= len(tables) <= 32, 'SOURCE_TABLE_SCOPE_INVALID')
    for name, identity in tables.items():
        need(re.fullmatch(r'ops_shadow_[a-z_]+', name) and isinstance(identity, list)
             and len(identity) == 2 and type(identity[0]) is int and 0 <= identity[0] <= 100_000
             and isinstance(identity[1], str) and SHA.fullmatch(identity[1]), 'SOURCE_TABLE_IDENTITY_INVALID')
    stamp(value['approved_at'])
    return value


def validate_manifest(record, writer_public_key, source_public_key, prefix='drop-rate'):
    need(writer_public_key != source_public_key, 'SOURCE_AND_WRITER_KEYS_MUST_DIFFER')
    value = verified(record, writer_public_key)
    need(set(value) == {'schema', 'source_approval', 'source_approval_sha256', 'execution_id',
         'created_at', 'key_id', 'nonce', 'sqlite_sha256', 'sqlite_bytes', 'ciphertext_sha256',
         'ciphertext_bytes', 'object_key', 'retention_until'}, 'BACKUP_MANIFEST_FIELDS')
    source = source_approval(value['source_approval'], source_public_key)
    need(value['schema'] == SCHEMA and value['source_approval_sha256'] == sha(
         canonical_json(value['source_approval'])), 'BACKUP_SOURCE_BINDING_MISMATCH')
    for field in ('execution_id', 'key_id'):
        need(isinstance(value[field], str) and ID.fullmatch(value[field]), 'BACKUP_ID_INVALID')
    for field in ('sqlite_sha256', 'ciphertext_sha256'):
        need(isinstance(value[field], str) and SHA.fullmatch(value[field]), 'BACKUP_DIGEST_INVALID')
    need(type(value['sqlite_bytes']) is int and 1 <= value['sqlite_bytes'] <= 64_000_000
         and type(value['ciphertext_bytes']) is int
         and value['ciphertext_bytes'] == value['sqlite_bytes'] + 16
         and value['ciphertext_bytes'] <= MAX_CIPHERTEXT, 'BACKUP_SIZE_INVALID')
    unb64(value['nonce'], 12)
    need(value['object_key'] == f'{prefix}/{PREFIX}/objects/{value["ciphertext_sha256"]}.sqlite.aesgcm',
         'BACKUP_OBJECT_KEY_MISMATCH')
    created, retained = stamp(value['created_at']), stamp(value['retention_until'])
    need(retained > created and created >= stamp(source['approved_at']), 'BACKUP_RETENTION_INVALID')
    return value, source


def aad(value):
    # Explicit binding prevents swapping source approvals, size, key or execution.
    return canonical_json({name: value[name] for name in (
        'schema', 'source_approval_sha256', 'execution_id', 'created_at', 'key_id',
        'sqlite_sha256', 'sqlite_bytes', 'retention_until')})


def decrypt(ciphertext, manifest, key):
    need(isinstance(key, bytes) and len(key) == 32, 'AES256_KEY_REQUIRED')
    need(len(ciphertext) == manifest['ciphertext_bytes'] and sha(ciphertext)
         == manifest['ciphertext_sha256'], 'CIPHERTEXT_IDENTITY_MISMATCH')
    try:
        raw = AESGCM(key).decrypt(unb64(manifest['nonce'], 12), ciphertext, aad(manifest))
    except Exception:
        raise BackupGuard('AUTHENTICATED_DECRYPTION_FAILED') from None
    need(len(raw) == manifest['sqlite_bytes'] and sha(raw) == manifest['sqlite_sha256'],
         'SQLITE_FILE_IDENTITY_MISMATCH')
    return raw
