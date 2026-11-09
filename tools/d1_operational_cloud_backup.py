"""Separately approved cloud D1 SQL export -> verified SQLite -> encrypted R2.

No production SQL mutations. Export DOES block D1 requests temporarily, so this
command is never dispatched by a push or schedule. Source approval must already
exist, independently signed. Raw SQL and SQLite stay in process memory only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import os
import re
import time
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.drive_archive_transfer import ArchiveTransfer
from app.operational_backup_contract import (
    DATABASE_NAME, PREFIX, MAX_CIPHERTEXT, canonical_json, decode_json, need,
    sha, signed, source_approval, stamp, unb64,
)
from d1_operational_cloud_restore import cloud_storage, encrypt_snapshot, reconstruct_sql, require_cloud

ACCOUNT = 'e4d4b363540e991048d2e1812d5ef53e'
ORIGIN = 'https://api.cloudflare.com/client/v4'
MAX_SQL_BYTES = 64_000_000


class ExportReader:
    def __init__(self, token, database_id, client=None):
        need(bool(token) and re.fullmatch(r'[a-f0-9-]{36}', database_id), 'D1_EXPORT_CONFIGURATION_REQUIRED')
        self.token, self.database_id = token, database_id
        self.client = client or httpx.Client(follow_redirects=False, timeout=25)
        self.path = f'/accounts/{ACCOUNT}/d1/database/{database_id}'

    def _read(self, method, url, *, body=None, authenticated=True, maximum=256_000):
        headers = {'Authorization': 'Bearer ' + self.token} if authenticated else {}
        # Never send Cloudflare bearer auth to the provider's signed SQL URL.
        with self.client.stream(method, url, headers=headers, json=body) as response:
            need(response.status_code == 200, 'CLOUD_EXPORT_HTTP_FAILED')
            size, chunks = 0, []
            for chunk in response.iter_bytes(65536):
                size += len(chunk)
                need(size <= maximum, 'CLOUD_EXPORT_RESPONSE_BOUND')
                chunks.append(chunk)
            return b''.join(chunks)

    def api(self, method, suffix='', body=None):
        need((method, suffix) in {('GET', ''), ('GET', '/time_travel/bookmark'), ('POST', '/export')},
             'D1_OPERATION_NOT_ALLOWED')
        value = decode_json(self._read(method, ORIGIN + self.path + suffix, body=body))
        need(value.get('success') is True and not value.get('errors'), 'D1_EXPORT_API_FAILED')
        need(isinstance(value.get('result'), dict), 'D1_EXPORT_RESULT_INVALID')
        return value['result']

    def bookmark(self):
        value = self.api('GET', '/time_travel/bookmark').get('bookmark')
        need(isinstance(value, str) and re.fullmatch(r'[a-f0-9-]{16,200}', value), 'D1_BOOKMARK_REQUIRED')
        return value

    def export_sql(self):
        metadata = self.api('GET')
        need(metadata.get('name') == DATABASE_NAME and metadata.get('uuid') == self.database_id,
             'D1_DATABASE_SCOPE_MISMATCH')
        before = self.bookmark()
        bookmark = None
        deadline = time.monotonic() + 90
        for _ in range(40):
            need(time.monotonic() < deadline, 'D1_EXPORT_POLL_TIMEOUT')
            body = {'output_format': 'polling'}
            if bookmark is not None:
                body['current_bookmark'] = bookmark
            result = self.api('POST', '/export', body)
            current = result.get('at_bookmark')
            need(current == before, 'D1_CHANGED_OR_EXPORT_BOOKMARK_UNVERIFIED')
            need(bookmark is None or current == bookmark, 'D1_EXPORT_BOOKMARK_CHANGED')
            bookmark = current
            need(result.get('status') != 'error', 'D1_EXPORT_FAILED')
            if result.get('status') == 'complete':
                url = result.get('result', {}).get('signed_url', '')
                parsed = urlsplit(url)
                need(parsed.scheme == 'https' and parsed.hostname
                     and parsed.hostname.endswith('.r2.cloudflarestorage.com')
                     and parsed.port in {None, 443} and not parsed.username and not parsed.password
                     and not parsed.fragment, 'D1_EXPORT_DOWNLOAD_HOST_UNAPPROVED')
                raw = self._read('GET', url, authenticated=False, maximum=MAX_SQL_BYTES)
                need(self.bookmark() == before, 'D1_CHANGED_DURING_EXPORT')
                return raw, before
            time.sleep(2)
        raise ValueError('D1_EXPORT_POLL_BOUND')


def put_immutable(service, key, data, mime):
    try:
        service.client.put_object(Bucket=service.config.bucket, Key=key,
            Body=io.BytesIO(data), IfNoneMatch='*', ContentType=mime, CacheControl='no-store',
            Metadata={'sha256': sha(data)})
    except Exception as exc:
        # A lost acknowledgement can be recovered by exact byte readback too.
        # Missing/different bytes fail; no unconditional overwrite is attempted.
        actual = service._read(key, len(data), expected_sha=sha(data), expected_size=len(data))
        need(actual == data, 'IMMUTABLE_OBJECT_CONFLICT')
    service._read(key, len(data), expected_sha=sha(data), expected_size=len(data))


def publish(service, ciphertext, record):
    manifest = record['payload']
    need(len(ciphertext) <= MAX_CIPHERTEXT, 'CIPHERTEXT_BOUND')
    data = canonical_json(record)
    digest = sha(data)
    put_immutable(service, manifest['object_key'], ciphertext, 'application/octet-stream')
    key = f'{service.config.prefix}/{PREFIX}/{digest}.manifest.json'
    put_immutable(service, key, data, 'application/json')
    # First binding wins. A concurrent different backup is INCOMPLETE/conflict,
    # never silently substituted. Orphan ciphertext is retained for review.
    execution = manifest['execution_id']
    reference = {'manifest_sha256': digest, 'source_approval_sha256': manifest['source_approval_sha256'],
                 'object_key': manifest['object_key'], 'sqlite_sha256': manifest['sqlite_sha256'],
                 'status': 'R2_BYTES_VERIFIED_OFFSITE_AND_INDEPENDENT_RESTORE_PENDING'}
    actual = service._create_once(f'{service.config.prefix}/{PREFIX}/executions/{execution}.json', reference)
    need(actual == reference, 'EXECUTION_ALREADY_BOUND_TO_OTHER_BACKUP')
    return actual


def main():
    try:
        require_cloud(os.environ)
        need(os.environ.get('DR_D1_EXPORT_APPROVED_SHA') == os.environ.get('GITHUB_SHA')
             and os.environ.get('DR_D1_EXPORT_APPROVED_RUN_ID') == os.environ.get('GITHUB_RUN_ID'),
             'EXACT_EXPORT_RUN_APPROVAL_REQUIRED')
        # Approval references are mandatory and attributable; flags alone are
        # not measurements or access-control proof. Environment review must
        # inspect the actual signed policy, billing and R2 lock evidence.
        for field in ('DR_D1_EXPORT_COST_APPROVAL_SHA256', 'DR_D1_EXPORT_SECURITY_APPROVAL_SHA256'):
            need(re.fullmatch(r'[a-f0-9]{64}', os.environ.get(field, '')), 'EXPORT_RELEASE_EVIDENCE_REQUIRED')
        approval = decode_json(os.environ['DR_D1_SOURCE_APPROVAL_JSON'].encode())
        source_key = unb64(os.environ['DR_D1_BACKUP_SOURCE_PUBLIC_KEY'], 32)
        source = source_approval(approval, source_key)
        service = cloud_storage(os.environ)
        run_id = os.environ['GITHUB_RUN_ID']
        need(run_id.isdigit(), 'INVALID_EXPORT_EXECUTION_ID')
        execution_key = f'{service.config.prefix}/{PREFIX}/executions/{run_id}.json'
        # An interrupted publish that recorded its execution must be verified
        # by the independent reader, never re-exported automatically.
        need(service._record(execution_key) is None, 'BACKUP_ALREADY_PUBLISHED_USE_INDEPENDENT_RESTORE')
        reader = ExportReader(os.environ['CLOUDFARE_D1_BACKUP_EXPORT_TOKEN'], source['database_id'])
        sql, bookmark = reader.export_sql()
        raw = reconstruct_sql(sql, source)
        del sql
        retention = os.environ['DR_D1_BACKUP_RETENTION_UNTIL']
        need(stamp(retention) > datetime.now(timezone.utc), 'RETENTION_APPROVAL_EXPIRED')
        ciphertext, record = encrypt_snapshot(raw, approval, source_key,
            Ed25519PrivateKey.from_private_bytes(unb64(os.environ['DR_D1_BACKUP_WRITER_PRIVATE_KEY'], 32)),
            key=unb64(os.environ['DR_D1_BACKUP_AES256_KEY'], 32),
            key_id=os.environ['DR_D1_BACKUP_KEY_ID'], execution_id=run_id,
            created_at=datetime.now(timezone.utc).isoformat(), retention_until=retention,
            prefix=service.config.prefix)
        del raw
        result = publish(service, ciphertext, record)
        # Only aggregate identifiers reach public logs. All source details and
        # bookmarks are in private receipts; no backup artifact upload exists.
        receipt = dict(result, export_bookmark=bookmark, export_run_reference=
            f'https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/{run_id}',
            source_postgres_writes=0, operational_d1_sql_writes=0)
        service._create_once(f'{service.config.prefix}/{PREFIX}/export-receipts/{run_id}.json', receipt)
        print(json.dumps({'status': result['status'], 'manifest_sha256': result['manifest_sha256'],
                          'operational_d1_sql_writes': 0, 'offsite_verified': False}))
    except Exception:
        raise SystemExit('Operational cloud backup INCOMPLETE; inspect private controls without logging data') from None


if __name__ == '__main__':
    main()
