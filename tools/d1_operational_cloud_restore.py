"""Cloud-only, memory-only restore and encryption for approved D1 snapshots.

CLI can only READ existing R2 ciphertext. No D1 client, export, SQL upload,
Google credential, production restore, local backup path or deletion endpoint.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
import sqlite3
import time

from app.operational_backup_contract import (
    SCHEMA, PREFIX, MAX_CIPHERTEXT, BackupGuard, AESGCM, aad, b64, canonical_json,
    decode_json, decrypt, need, sha, signed, source_approval, unb64, validate_manifest,
)
from app.drive_archive_transfer import ArchiveTransfer
from app.object_storage import ObjectStorageConfig
import d1_operational_restore_drill as restore


def identity(connection):
    connection.row_factory = sqlite3.Row
    tables = restore._schema(connection)
    return {'schema_sha256': sha(canonical_json(restore._objects(connection))),
            'table_fingerprints': {name: list(value) for name, value
                                   in restore._fingerprint(connection, tables).items()}}


def restore_bytes(raw, source):
    need(isinstance(raw, bytes) and raw.startswith(b'SQLite format 3\x00') and raw[18:20] == b'\x01\x01'
         and 0 < len(raw) <= restore.MAX_FILE_BYTES, 'STANDALONE_SQLITE_REQUIRED')
    with closing(sqlite3.connect(':memory:')) as original, closing(sqlite3.connect(':memory:')) as target:
        original.deserialize(raw)
        original.execute('PRAGMA temp_store=MEMORY')
        actual = identity(original)
        need(all(actual[field] == source[field] for field in actual), 'INDEPENDENT_SOURCE_PARITY_MISMATCH')
        result = restore.restore_database(original, target, source['generation_sha256'])
    return result


def reconstruct_sql(sql, source):
    """Untrusted supported D1 SQL output, never arbitrary file access.

    No missing schema objects are synthesized. Normalized/lost DDL, skipped
    tables, JS numeric rounding or mixed source state fail independent parity.
    A live export adapter/consistent source evidence remains a release gate.
    """
    need(isinstance(sql, bytes) and 0 < len(sql) <= restore.MAX_FILE_BYTES, 'SQL_EXPORT_BOUND')
    deadline = time.monotonic() + 30
    with closing(sqlite3.connect(':memory:')) as conn:
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.execute('PRAGMA journal_mode=MEMORY')
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 2_000_000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        conn.execute('PRAGMA max_page_count=15625')
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        denied = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_CREATE_VTABLE,
                  sqlite3.SQLITE_DROP_VTABLE, sqlite3.SQLITE_CREATE_TEMP_TABLE,
                  sqlite3.SQLITE_CREATE_TEMP_INDEX, sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
                  sqlite3.SQLITE_CREATE_TEMP_VIEW}

        def authorize(action, one, two, database, trigger):
            if action in denied or database not in {None, 'main'}:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_FUNCTION and two not in {'length', 'json_valid'}:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA and not (
                one in {'foreign_keys', 'defer_foreign_keys'} and str(two).lower() in {'on', 'off', 'true', 'false', '1', '0'}):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        try:
            conn.executescript(sql.decode('utf-8'))
            conn.commit()
        except Exception:
            raise BackupGuard('SQL_EXPORT_RECONSTRUCTION_FAILED') from None
        finally:
            conn.set_authorizer(None)
            conn.set_progress_handler(None, 0)
        conn.row_factory = sqlite3.Row
        raw = conn.serialize()
    restore_bytes(raw, source)
    return raw


def encrypt_snapshot(raw, approval, source_public_key, writer_private_key, *, key, key_id,
                     execution_id, created_at, retention_until, prefix='drop-rate'):
    source = source_approval(approval, source_public_key)
    need(len(key) == 32, 'AES256_KEY_REQUIRED')
    restore_bytes(raw, source)
    need(len(raw) + 16 <= MAX_CIPHERTEXT, 'BACKUP_EXCEEDS_REVIEWED_DRIVE_BOUND')
    value = dict(schema=SCHEMA, source_approval=approval,
        source_approval_sha256=sha(canonical_json(approval)), execution_id=execution_id,
        created_at=created_at, retention_until=retention_until, key_id=key_id,
        nonce=b64(os.urandom(12)), sqlite_sha256=sha(raw), sqlite_bytes=len(raw))
    ciphertext = AESGCM(key).encrypt(unb64(value['nonce'], 12), raw, aad(value))
    value.update(ciphertext_sha256=sha(ciphertext), ciphertext_bytes=len(ciphertext),
                 object_key=f'{prefix}/{PREFIX}/objects/{sha(ciphertext)}.sqlite.aesgcm')
    record = signed(value, writer_private_key)
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    public = writer_private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    validate_manifest(record, public, source_public_key, prefix)
    return ciphertext, record


def verify_cloud_copy(ciphertext, record, *, writer_public_key, source_public_key,
                      key, expected_manifest_sha256, expected_file_sha256,
                      expected_generation_sha256, prefix='drop-rate'):
    # All three pins come from the protected, separately retained approval.
    need(sha(canonical_json(record)) == expected_manifest_sha256, 'INDEPENDENT_MANIFEST_PIN_MISMATCH')
    value, source = validate_manifest(record, writer_public_key, source_public_key, prefix)
    need(value['sqlite_sha256'] == expected_file_sha256
         and source['generation_sha256'] == expected_generation_sha256, 'INDEPENDENT_PIN_MISMATCH')
    raw = decrypt(ciphertext, value, key)
    result = restore_bytes(raw, source)
    result.update(status='CLOUD_MEMORY_SQLITE_RESTORE_VERIFIED',
        sqlite_file_sha256=expected_file_sha256, ciphertext_sha256=sha(ciphertext),
        manifest_sha256=expected_manifest_sha256, source_approval_sha256=value['source_approval_sha256'],
        cloud_sqlite_restore_verified=True, local_disposable_restore_only=False,
        real_d1_restore_verified=False, interrupted_generation_resume_executed=False,
        remote_d1_writes=0, source_postgres_writes=0,
        verification_scope='NINE_OPERATIONAL_SOURCE_TABLES_AND_TRACKED_SHADOW_METADATA')
    return result


def require_cloud(env):
    need(env.get('GITHUB_ACTIONS') == 'true' and env.get('RUNNER_ENVIRONMENT') == 'github-hosted'
         and env.get('RUNNER_OS') == 'Linux' and env.get('GITHUB_REPOSITORY')
         == 'pulltheorytcg/drop-rate-backend' and env.get('GITHUB_REF') == 'refs/heads/main'
         and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'PROTECTED_CLOUD_RUNNER_REQUIRED')


def cloud_storage(env):
    # Require a separately issued, short-lived R2 session. The protected release
    # review verifies its exact object/prefix scope, TTL and bucket-lock policy.
    session = env.get('DR_D1_BACKUP_R2_SESSION_TOKEN', '')
    need(bool(session), 'SCOPED_R2_SESSION_REQUIRED')
    config = ObjectStorageConfig.from_env()
    need(config is not None and config.bucket == 'drop-rate-private' and config.prefix == 'drop-rate'
         and config.endpoint.rstrip('/') ==
         'https://e4d4b363540e991048d2e1812d5ef53e.eu.r2.cloudflarestorage.com',
         'APPROVED_PRIVATE_EU_R2_REQUIRED')
    return ArchiveTransfer(config, session_token=session)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()  # No private local files, arbitrary URLs or database selectors.
    try:
        require_cloud(os.environ)
        need(os.environ.get('DR_D1_RESTORE_APPROVED_SHA') == os.environ.get('GITHUB_SHA')
             and os.environ.get('DR_D1_RESTORE_APPROVED_RUN_ID') == os.environ.get('GITHUB_RUN_ID'),
             'EXACT_RUN_APPROVAL_REQUIRED')
        service = cloud_storage(os.environ)
        manifest_sha = os.environ['DR_D1_BACKUP_MANIFEST_SHA256']
        need(restore.SHA.fullmatch(manifest_sha), 'INVALID_MANIFEST_PIN')
        data = service._read(f'{service.config.prefix}/{PREFIX}/{manifest_sha}.manifest.json',
                             256_000, expected_sha=manifest_sha)
        record = decode_json(data)
        writer_key = unb64(os.environ['DR_D1_BACKUP_WRITER_PUBLIC_KEY'], 32)
        source_key = unb64(os.environ['DR_D1_BACKUP_SOURCE_PUBLIC_KEY'], 32)
        value, _ = validate_manifest(record, writer_key, source_key, service.config.prefix)
        ciphertext = service._read(value['object_key'], MAX_CIPHERTEXT,
            expected_sha=value['ciphertext_sha256'], expected_size=value['ciphertext_bytes'])
        result = verify_cloud_copy(ciphertext, record, writer_public_key=writer_key,
            source_public_key=source_key, key=unb64(os.environ['DR_D1_BACKUP_AES256_KEY'], 32),
            expected_manifest_sha256=manifest_sha,
            expected_file_sha256=os.environ['DR_D1_BACKUP_SQLITE_SHA256'],
            expected_generation_sha256=os.environ['DR_D1_BACKUP_GENERATION_SHA256'],
            prefix=service.config.prefix)
        # The receipt is private R2, not a public CI artifact/log. The workflow
        # run URL independently attributes execution; no signing key on reader.
        result.update(verifier_reference=f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}'
            f'/actions/runs/{os.environ["GITHUB_RUN_ID"]}',
            verified_at=datetime.now(timezone.utc).isoformat())
        run = os.environ['GITHUB_RUN_ID']
        need(run.isdigit(), 'INVALID_RUN_ID')
        receipt_key = f'{service.config.prefix}/{PREFIX}/restore-receipts/{manifest_sha}/{run}.json'
        actual = service._create_once(receipt_key, result)
        need(set(actual) == set(result) and all(actual[name] == value for name, value in result.items()
             if name != 'verified_at'), 'RESTORE_RECEIPT_CONFLICT')
        print(json.dumps({'status': 'CLOUD_MEMORY_SQLITE_RESTORE_VERIFIED',
            'receipt_sha256': sha(canonical_json(actual)), 'production_writes': 0,
            'all_150_relations_restored': False, 'gate_a_complete': False, 'gate_h_complete': False}))
    except Exception:
        raise SystemExit('Operational cloud restore FAILED; inspect private controls, never log payloads') from None


if __name__ == '__main__':
    main()
