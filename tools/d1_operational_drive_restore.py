"""Emergency cloud-memory restore from Drive when Cloudflare is unavailable.

Read-only Google requests. No R2 credential/client, local file or refresh token.
The cloud credential broker supplies a short-lived Google access token.
"""
from __future__ import annotations

import json
import os
import re

import httpx

from app.drive_archive_transfer import EXPECTED_ACCOUNT, OPERATIONAL_FOLDER
from app.operational_backup_contract import MAX_CIPHERTEXT, canonical_json, decode_json, need, sha, unb64, validate_manifest
from d1_operational_cloud_restore import require_cloud, verify_cloud_copy

ORIGIN = 'https://www.googleapis.com/drive/v3'


class DriveReader:
    def __init__(self, token, client=None):
        need(bool(token), 'GOOGLE_CLOUD_ACCESS_TOKEN_REQUIRED')
        self.token = token
        self.client = client or httpx.Client(follow_redirects=False, timeout=25)

    def read(self, path, *, maximum=256_000):
        need(path == '/about?fields=user(emailAddress,permissionId)' or re.fullmatch(
            r'/files/[A-Za-z0-9_-]{10,200}\?(?:alt=media|fields=[A-Za-z0-9(),]+)', path),
             'GOOGLE_READ_PATH_INVALID')
        data, size = [], 0
        with self.client.stream('GET', ORIGIN + path,
            headers={'Authorization': 'Bearer ' + self.token}) as response:
            need(response.status_code == 200, 'GOOGLE_PRIVATE_READ_FAILED')
            for chunk in response.iter_bytes(65536):
                size += len(chunk)
                need(size <= maximum, 'GOOGLE_RESPONSE_BOUND')
                data.append(chunk)
        return b''.join(data)

    def metadata(self, file_id):
        need(isinstance(file_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{10,200}', file_id), 'GOOGLE_FILE_ID_INVALID')
        return decode_json(self.read('/files/' + file_id + '?fields=id,name,mimeType,size,parents,'
            'owners(emailAddress,permissionId),permissions(role,type,emailAddress),shared,trashed,appProperties'))

    @staticmethod
    def private(value, permission):
        need(value.get('shared') is False and value.get('trashed') is False
             and value.get('owners') == [{'emailAddress': EXPECTED_ACCOUNT, 'permissionId': permission}]
             and value.get('permissions') == [{'role': 'owner', 'type': 'user', 'emailAddress': EXPECTED_ACCOUNT}],
             'GOOGLE_OWNER_ONLY_REQUIRED')

    def fetch(self, manifest_file_id, ciphertext_file_id, expected_manifest_sha, writer_key, source_key):
        about = decode_json(self.read('/about?fields=user(emailAddress,permissionId)')).get('user', {})
        permission = about.get('permissionId')
        need(about.get('emailAddress') == EXPECTED_ACCOUNT and isinstance(permission, str) and permission,
             'GOOGLE_AUTHENTICATED_ACCOUNT_MISMATCH')
        folder = self.metadata(OPERATIONAL_FOLDER)
        self.private(folder, permission)
        need(folder.get('id') == OPERATIONAL_FOLDER and folder.get('name') == 'Drop Rate – Operational D1 Backups'
             and folder.get('mimeType') == 'application/vnd.google-apps.folder', 'GOOGLE_FOLDER_MISMATCH')
        need(manifest_file_id != ciphertext_file_id, 'GOOGLE_DISTINCT_MEMBERS_REQUIRED')
        raw = self.read('/files/' + manifest_file_id + '?alt=media')
        need(sha(raw) == expected_manifest_sha, 'INDEPENDENT_DRIVE_MANIFEST_PIN_MISMATCH')
        record = decode_json(raw)
        value, _ = validate_manifest(record, writer_key, source_key)
        identities = [(manifest_file_id, expected_manifest_sha, len(raw), '.manifest.json', 'application/json'),
                      (ciphertext_file_id, value['ciphertext_sha256'], value['ciphertext_bytes'],
                       '.sqlite.aesgcm', 'application/octet-stream')]
        for file_id, digest, size, suffix, mime in identities:
            metadata = self.metadata(file_id)
            self.private(metadata, permission)
            need(metadata.get('id') == file_id and metadata.get('parents') == [OPERATIONAL_FOLDER]
                 and metadata.get('mimeType') == mime and metadata.get('size') == str(size)
                 and metadata.get('name') == f'drop-rate-operational_d1_sqlite-{digest}{suffix}'
                 and metadata.get('appProperties') == {'drSchema': 'drive-copy-v1', 'drKind': 'OPERATIONAL_D1_SQLITE',
                    'drManifest': expected_manifest_sha, 'drObject': digest}, 'GOOGLE_MEMBER_IDENTITY_MISMATCH')
        # A fresh provider download, never the earlier R2 buffer or metadata SHA.
        ciphertext = self.read('/files/' + ciphertext_file_id + '?alt=media', maximum=MAX_CIPHERTEXT)
        return ciphertext, record


def main():
    try:
        require_cloud(os.environ)
        need(os.environ.get('DR_D1_RESTORE_APPROVED_SHA') == os.environ.get('GITHUB_SHA')
             and os.environ.get('DR_D1_RESTORE_APPROVED_RUN_ID') == os.environ.get('GITHUB_RUN_ID'),
             'EXACT_RUN_APPROVAL_REQUIRED')
        writer_key = unb64(os.environ['DR_D1_BACKUP_WRITER_PUBLIC_KEY'], 32)
        source_key = unb64(os.environ['DR_D1_BACKUP_SOURCE_PUBLIC_KEY'], 32)
        manifest_sha = os.environ['DR_D1_BACKUP_MANIFEST_SHA256']
        reader = DriveReader(os.environ['DR_D1_GOOGLE_ACCESS_TOKEN'])
        ciphertext, record = reader.fetch(os.environ['DR_D1_DRIVE_MANIFEST_FILE_ID'],
            os.environ['DR_D1_DRIVE_CIPHERTEXT_FILE_ID'], manifest_sha, writer_key, source_key)
        report = verify_cloud_copy(ciphertext, record, writer_public_key=writer_key, source_public_key=source_key,
            key=unb64(os.environ['DR_D1_BACKUP_AES256_KEY'], 32), expected_manifest_sha256=manifest_sha,
            expected_file_sha256=os.environ['DR_D1_BACKUP_SQLITE_SHA256'],
            expected_generation_sha256=os.environ['DR_D1_BACKUP_GENERATION_SHA256'])
        # Public receipt contains identities/aggregate booleans only. GitHub run
        # logs attribute verification without needing a working Cloudflare account.
        print(json.dumps(dict(status='GOOGLE_DRIVE_CLOUD_MEMORY_RESTORE_VERIFIED',
            manifest_sha256=manifest_sha, sqlite_sha256=report['sqlite_file_sha256'],
            generation_sha256=report['generation_sha256'], private_report_sha256=sha(canonical_json(report)),
            cloudflare_access_required=False, operational_d1_sql_writes=0,
            google_writes=0, all_150_relations_restored=False, gate_a_complete=False, gate_h_complete=False)))
    except Exception:
        raise SystemExit('Operational off-site cloud restore FAILED; no private data logged') from None


if __name__ == '__main__':
    main()
