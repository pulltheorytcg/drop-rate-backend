"""Synthetic private snapshots only. Real bytes never leave these fixtures."""
import copy
import io
import json
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import d1_operational_cloud_restore as cloud
import d1_operational_drive_restore as offsite
import httpx
from app import operational_backup_contract as contract
from app import drive_archive_transfer as transfer
from test_d1_operational_restore_drill import snapshot
from test_drive_archive_transfer import FakeS3, destination
from app.object_storage import ObjectStorageConfig


def public(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


@pytest.fixture
def backup(snapshot):
    db, _, _, _, generation, path, _ = snapshot
    evidence_key, writer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    source = dict(schema=contract.SOURCE_SCHEMA, database_name=contract.DATABASE_NAME,
        database_id='00000000-0000-0000-0000-000000000001',
        generation_sha256=generation, generation_id='src-' + generation[:32],
        evidence_reference='https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/123',
        evidence_sha256='a' * 64, approved_at='2026-11-09T00:00:00Z', **cloud.identity(db.con))
    approval = contract.signed(source, evidence_key)
    key = b'k' * 32
    raw = path.read_bytes()
    ciphertext, record = cloud.encrypt_snapshot(raw, approval, public(evidence_key), writer,
        key=key, key_id='fixture-key', execution_id='fixture-execution-1',
        created_at='2026-11-09T12:00:00Z', retention_until='2026-12-09T12:00:00Z')
    args = dict(writer_public_key=public(writer), source_public_key=public(evidence_key),
        key=key, expected_manifest_sha256=contract.sha(contract.canonical_json(record)),
        expected_file_sha256=contract.sha(raw), expected_generation_sha256=generation)
    return ciphertext, record, args, writer, source, raw


def test_cloud_restore_uses_exact_memory_bytes_and_existing_nine_table_rules(backup):
    ciphertext, record, args, _, _, raw = backup
    result = cloud.verify_cloud_copy(ciphertext, record, **args)
    assert result['cloud_sqlite_restore_verified'] is True
    assert len(result['verified_tables']) == 9
    assert result['remote_d1_writes'] == result['source_postgres_writes'] == 0
    assert result['gate_a_complete'] is result['gate_h_complete'] is False
    assert result['all_150_relations_restored'] is result['real_d1_restore_verified'] is False
    assert raw[:100] not in ciphertext
    assert b'Founder' not in ciphertext


@pytest.mark.parametrize('field,value', [
    ('expected_file_sha256', '0' * 64), ('expected_generation_sha256', '0' * 64),
    ('expected_manifest_sha256', '0' * 64), ('key', b'x' * 32),
])
def test_independent_pins_and_encryption_key_fail_closed(backup, field, value):
    ciphertext, record, args, *_ = backup
    with pytest.raises(contract.BackupGuard):
        cloud.verify_cloud_copy(ciphertext, record, **(args | {field: value}))


def test_ciphertext_corruption_and_manifest_substitution_fail(backup):
    ciphertext, record, args, *_ = backup
    with pytest.raises(contract.BackupGuard, match='CIPHERTEXT_IDENTITY'):
        cloud.verify_cloud_copy(ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]), record, **args)
    edited = copy.deepcopy(record)
    edited['payload']['object_key'] = 'drop-rate/private-media/secret'
    args['expected_manifest_sha256'] = contract.sha(contract.canonical_json(edited))
    with pytest.raises(contract.BackupGuard, match='SIGNATURE'):
        cloud.verify_cloud_copy(ciphertext, edited, **args)


def test_writer_cannot_forge_separate_source_evidence(backup):
    ciphertext, record, args, writer, *_ = backup
    edited = copy.deepcopy(record['payload'])
    edited['source_approval']['payload']['generation_sha256'] = 'f' * 64
    edited['source_approval_sha256'] = contract.sha(contract.canonical_json(edited['source_approval']))
    record = contract.signed(edited, writer)
    with pytest.raises(contract.BackupGuard, match='SIGNATURE'):
        contract.validate_manifest(record, args['writer_public_key'], args['source_public_key'])
    with pytest.raises(contract.BackupGuard, match='MUST_DIFFER'):
        contract.validate_manifest(record, args['writer_public_key'], args['writer_public_key'])


def test_independent_full_table_digests_prevent_self_consistent_modified_snapshot(backup):
    _, _, _, _, source, raw = backup
    db = sqlite3.connect(':memory:')
    db.deserialize(raw)
    db.execute('UPDATE ops_shadow_inventory SET market_value_minor=999')
    db.commit()
    with pytest.raises(contract.BackupGuard, match='INDEPENDENT_SOURCE_PARITY'):
        cloud.restore_bytes(db.serialize(), source)
    db.close()


def test_memory_restore_rejects_snapshot_header_requiring_missing_wal(backup):
    raw, source = backup[5], backup[4]
    with pytest.raises(contract.BackupGuard, match='STANDALONE_SQLITE'):
        cloud.restore_bytes(raw[:18] + b'\x02\x02' + raw[20:], source)


def test_sql_export_reconstruction_preserves_complete_schema_and_every_row(backup):
    _, _, _, _, source, raw = backup
    db = sqlite3.connect(':memory:')
    db.deserialize(raw)
    sql = ('\n'.join(db.iterdump())).encode()
    db.close()
    reconstructed = cloud.reconstruct_sql(sql, source)
    assert cloud.restore_bytes(reconstructed, source)['owner_currency_balances_preserved']


@pytest.mark.parametrize('sql', [
    b"ATTACH DATABASE '/tmp/private-operational.sqlite' AS leak;",
    b"SELECT load_extension('untrusted');", b'PRAGMA writable_schema=ON;',
    b'CREATE VIRTUAL TABLE secret USING fts5(data);',
])
def test_reconstruction_never_allows_external_files_extensions_or_schema_bypass(backup, sql):
    source = backup[4]
    with pytest.raises(contract.BackupGuard, match='RECONSTRUCTION_FAILED'):
        cloud.reconstruct_sql(sql, source)


def test_cloud_cli_rejects_local_self_hosted_or_pull_request_context():
    good = dict(GITHUB_ACTIONS='true', RUNNER_ENVIRONMENT='github-hosted', RUNNER_OS='Linux',
        GITHUB_REPOSITORY='pulltheorytcg/drop-rate-backend', GITHUB_REF='refs/heads/main',
        GITHUB_EVENT_NAME='workflow_dispatch')
    cloud.require_cloud(good)
    for field in good:
        with pytest.raises(contract.BackupGuard, match='PROTECTED_CLOUD'):
            cloud.require_cloud(good | {field: 'invalid'})


def test_google_independent_readback_can_restore_without_cloudflare(backup):
    ciphertext, record, args, *_ = backup
    manifest = contract.canonical_json(record)
    manifest_id, ciphertext_id = 'synthetic-manifest-id', 'synthetic-ciphertext-id'
    folder = transfer.OPERATIONAL_FOLDER
    permission = 'synthetic-permission'
    private = dict(owners=[dict(emailAddress=transfer.EXPECTED_ACCOUNT, permissionId=permission)],
        permissions=[dict(role='owner', type='user', emailAddress=transfer.EXPECTED_ACCOUNT)], shared=False, trashed=False)

    def handler(request):
        assert request.method == 'GET' and request.url.host == 'www.googleapis.com'
        assert request.headers['authorization'] == 'Bearer synthetic-google-only'
        if request.url.path.endswith('/about'):
            return httpx.Response(200, json={'user': dict(emailAddress=transfer.EXPECTED_ACCOUNT, permissionId=permission)})
        file_id = request.url.path.split('/')[-1]
        if request.url.params.get('alt') == 'media':
            return httpx.Response(200, content=manifest if file_id == manifest_id else ciphertext)
        if file_id == folder:
            value = dict(id=folder, name='Drop Rate – Operational D1 Backups', mimeType='application/vnd.google-apps.folder', **private)
        else:
            is_manifest = file_id == manifest_id
            data = manifest if is_manifest else ciphertext
            digest = contract.sha(data)
            suffix = '.manifest.json' if is_manifest else '.sqlite.aesgcm'
            value = dict(id=file_id, name=f'drop-rate-operational_d1_sqlite-{digest}{suffix}',
                mimeType='application/json' if is_manifest else 'application/octet-stream',
                size=str(len(data)), parents=[folder], appProperties=dict(drSchema='drive-copy-v1',
                    drKind='OPERATIONAL_D1_SQLITE', drManifest=args['expected_manifest_sha256'], drObject=digest), **private)
        return httpx.Response(200, json=value)

    reader = offsite.DriveReader('synthetic-google-only', httpx.Client(transport=httpx.MockTransport(handler)))
    downloaded, pinned = reader.fetch(manifest_id, ciphertext_id, args['expected_manifest_sha256'],
        args['writer_public_key'], args['source_public_key'])
    assert cloud.verify_cloud_copy(downloaded, pinned, **args)['cloud_sqlite_restore_verified']
    with pytest.raises(contract.BackupGuard, match='MANIFEST_PIN'):
        reader.fetch(manifest_id, ciphertext_id, '0'*64, args['writer_public_key'], args['source_public_key'])


def test_cloud_storage_rejects_unscoped_legacy_credentials():
    with pytest.raises(contract.BackupGuard, match='SCOPED_R2_SESSION'):
        cloud.cloud_storage({})


def test_operational_drive_kind_disabled_and_separate_from_pricing_folder(monkeypatch):
    monkeypatch.delenv('TCG_OPERATIONAL_D1_DRIVE_TRANSFER_ENABLED', raising=False)
    with pytest.raises(transfer.ArchiveTransferError, match='TRANSFER_DISABLED'):
        transfer.destination_for_kind('OPERATIONAL_D1_SQLITE')
    monkeypatch.setenv('TCG_OPERATIONAL_D1_DRIVE_TRANSFER_ENABLED', 'true')
    monkeypatch.setenv('TCG_OPERATIONAL_D1_DRIVE_FOLDER_ID', transfer.EXPECTED_FOLDER)
    with pytest.raises(transfer.ArchiveTransferError, match='UNCONFIGURED'):
        transfer.destination_for_kind('OPERATIONAL_D1_SQLITE')


def test_existing_transfer_reservation_fresh_readback_and_completion_for_ciphertext(backup, monkeypatch):
    ciphertext, record, args, *_ = backup
    folder = transfer.OPERATIONAL_FOLDER
    monkeypatch.setenv('TCG_OPERATIONAL_D1_DRIVE_TRANSFER_ENABLED', 'true')
    monkeypatch.setenv('TCG_OPERATIONAL_D1_DRIVE_FOLDER_ID', folder)
    monkeypatch.setenv('DR_D1_BACKUP_WRITER_PUBLIC_KEY', contract.b64(args['writer_public_key']))
    monkeypatch.setenv('DR_D1_BACKUP_SOURCE_PUBLIC_KEY', contract.b64(args['source_public_key']))
    service = transfer.ArchiveTransfer(ObjectStorageConfig(
        'https://fixture.invalid', 'fixture', 'auto', 'fixture', 'fixture'), FakeS3())
    manifest_bytes = contract.canonical_json(record)
    manifest_sha = contract.sha(manifest_bytes)
    service.client.objects[record['payload']['object_key']] = ciphertext
    service.client.objects[f'drop-rate/{contract.PREFIX}/{manifest_sha}.manifest.json'] = manifest_bytes
    bundle = service.load_archive('OPERATIONAL_D1_SQLITE', manifest_sha)
    assert bundle.members[0].suffix == '.sqlite.aesgcm'
    assert len(bundle.members) == 2
    for index, member in enumerate(bundle.members):
        reserved = service.reserve(bundle, member, f'synthetic-drive-file-{index}')
        metadata = dict(id=reserved['file_id'], name=reserved['file_name'], parents=[folder],
            owner_email=transfer.EXPECTED_ACCOUNT, owner_permission_id='owner-permission-1',
            shared=False, trashed=False, mime_type=member.mime_type, size_bytes=member.size_bytes,
            app_properties=reserved['app_properties'])
        with pytest.raises(transfer.ArchiveTransferError, match='READBACK_MISMATCH'):
            service.record_verified_bytes(bundle, member, metadata, actual_sha256='0' * 64,
                actual_size=member.size_bytes, execution_id='fixture', account_permission_id='owner-permission-1')
        with pytest.raises(transfer.ArchiveTransferError, match='INCOMPLETE'):
            service.complete(bundle, 'fixture')
        data = service.client.objects[member.key]  # Simulated NEW Drive download, no real transfer claim.
        service.record_verified_bytes(bundle, member, metadata, actual_sha256=contract.sha(data),
            actual_size=len(data), execution_id='fixture', account_permission_id='owner-permission-1')
    assert service.complete(bundle, 'fixture')['objects_verified'] == 2
    assert service.complete(bundle, 'retry')['objects_verified'] == 2
    evidence = destination() | dict(folder_id=folder, folder_name='Drop Rate – Operational D1 Backups')
    transfer.validate_destination(evidence, kind='OPERATIONAL_D1_SQLITE')
    with pytest.raises(transfer.ArchiveTransferError, match='DESTINATION_MISMATCH'):
        transfer.validate_destination(destination(), kind='OPERATIONAL_D1_SQLITE')
