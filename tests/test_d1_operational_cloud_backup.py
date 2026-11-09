"""No cloud operations: supported API contract, interruptions and gating."""
from pathlib import Path
import json
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import d1_operational_cloud_backup as writer
import d1_operational_cloud_restore as cloud
from app.operational_backup_contract import BackupGuard, DATABASE_NAME, sha, canonical_json
from app.drive_archive_transfer import ArchiveTransfer
from app.object_storage import ObjectStorageConfig
from test_drive_archive_transfer import FakeS3
from test_d1_operational_cloud_restore import backup, public, snapshot

DB = '00000000-0000-0000-0000-000000000001'
BOOKMARK = '00000001-00000002-00000003-' + 'a' * 32


def export_client(*, concurrent=False, host='export.fixture.r2.cloudflarestorage.com', redirect=False):
    calls, bookmark_calls = [], []

    def handler(request):
        calls.append(request)
        if request.url.host == host:
            assert 'authorization' not in request.headers
            if redirect:
                return httpx.Response(302, headers={'Location': 'https://untrusted.invalid/private'})
            return httpx.Response(200, content=b'-- synthetic SQL only')
        assert request.headers['authorization'] == 'Bearer synthetic-token'
        if request.url.path.endswith('/time_travel/bookmark'):
            bookmark_calls.append(1)
            value = BOOKMARK + ('b' if concurrent and len(bookmark_calls) > 1 else '')
            result = {'bookmark': value}
        elif request.url.path.endswith('/export'):
            assert request.method == 'POST' and json.loads(request.content) == {'output_format': 'polling'}
            result = {'status': 'complete', 'at_bookmark': BOOKMARK,
                      'result': {'signed_url': f'https://{host}/private?signature=synthetic'}}
        else:
            result = {'name': DATABASE_NAME, 'uuid': DB}
        return httpx.Response(200, json={'success': True, 'result': result})

    return writer.ExportReader('synthetic-token', DB, httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False)), calls


def test_supported_export_uses_stable_bookmark_and_never_sends_token_to_download():
    reader, calls = export_client()
    assert reader.export_sql() == (b'-- synthetic SQL only', BOOKMARK)
    assert len(calls) == 5
    assert all('/restore' not in str(call.url) and '/query' not in str(call.url) for call in calls)


@pytest.mark.parametrize('options', [dict(concurrent=True), dict(host='untrusted.invalid'), dict(redirect=True)])
def test_change_unsafe_download_host_and_redirect_fail_closed(options):
    reader, _ = export_client(**options)
    with pytest.raises(BackupGuard):
        reader.export_sql()


def test_export_client_cannot_mutate_or_restore_source():
    reader, calls = export_client()
    for method, path in [('POST', '/query'), ('POST', '/time_travel/restore'), ('DELETE', '')]:
        with pytest.raises(BackupGuard, match='NOT_ALLOWED'):
            reader.api(method, path)
    assert calls == []


def test_immutable_r2_publish_and_retry_cannot_change_execution_binding(backup):
    ciphertext, record, args, writer_key, source, raw = backup
    service = ArchiveTransfer(ObjectStorageConfig('https://fixture.invalid', 'fixture', 'auto', 'x', 'y'), FakeS3())
    first = writer.publish(service, ciphertext, record)
    assert writer.publish(service, ciphertext, record) == first
    assert first['status'].endswith('PENDING')
    assert all(call[0] != 'delete' for call in service.client.calls)
    assert service.client.objects[first['object_key']] == ciphertext
    manifest_key = f'drop-rate/operational-d1-backups/v1/{first["manifest_sha256"]}.manifest.json'
    assert sha(service.client.objects[manifest_key]) == first['manifest_sha256']
    another, second = cloud.encrypt_snapshot(raw, record['payload']['source_approval'], args['source_public_key'],
        writer_key, key=args['key'], key_id=record['payload']['key_id'],
        execution_id=record['payload']['execution_id'], created_at=record['payload']['created_at'],
        retention_until=record['payload']['retention_until'])
    with pytest.raises(BackupGuard, match='EXECUTION_ALREADY_BOUND'):
        writer.publish(service, another, second)
    assert writer.publish(service, ciphertext, record) == first


def test_cloud_workflow_never_exports_on_push_pr_schedule_or_partial_approval():
    src = Path('.github/workflows/d1-operational-cloud-dr.yml').read_text()
    assert 'schedule:' not in src and 'upload-artifact' not in src and 'actions/cache' not in src
    assert 'group: private-operational-d1-real-source-single-writer' in src
    assert src.count("github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'") == 3
    for operation in ('EXPORT', 'RESTORE'):
        assert f'vars.DR_D1_{operation}_APPROVED_SHA == github.sha' in src
        assert f'vars.DR_D1_{operation}_APPROVED_RUN_ID == github.run_id' in src
    restore_job = src.split('  restore-existing:\n')[1]
    assert 'CLOUDFLARE_D1_BACKUP_EXPORT_TOKEN' not in restore_job
    assert 'WRITER_PRIVATE_KEY' not in restore_job
    assert src.count('sudo swapoff -a') == 3 and src.count('ulimit -c 0') == 3
    drive_job = src.split('  restore-drive-existing:\n')[1]
    assert 'TCG_OBJECT_STORE' not in drive_job and 'CLOUDFLARE_' not in drive_job
