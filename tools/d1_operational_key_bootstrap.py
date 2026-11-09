"""One-time CLOUD-ONLY key provisioning to already-protected GitHub environments.

No environment creation, permission changes, old-key replacement, export or
backup data. Requires a separately approved short-lived environment-write
credential; GITHUB_TOKEN is not assumed to have that permission.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from app.operational_backup_contract import b64, need, sha, unb64
from d1_operational_cloud_restore import require_cloud

REPO = 'pulltheorytcg/drop-rate-backend'
ENVIRONMENTS = {
    'source': 'operational-d1-source-approval',
    'writer': 'operational-d1-backup-export',
    'restore': 'operational-d1-backup-restore',
    'drive': 'operational-d1-backup-drive-restore',
}
PROVISION_ENVIRONMENT = 'operational-d1-key-provision'
REFERENCE_NAMES = {'DR_D1_BACKUP_AES256_SECRET_NAME', 'DR_D1_BACKUP_WRITER_SECRET_NAME',
                   'DR_D1_BACKUP_SOURCE_SECRET_NAME', 'DR_D1_BACKUP_KEY_ID',
                   'DR_D1_BACKUP_SOURCE_PUBLIC_KEY', 'DR_D1_BACKUP_WRITER_PUBLIC_KEY',
                   'DR_D1_BACKUP_AES256_SHA256'}


def protected_environment(value, expected_name):
    need(value.get('name') == expected_name and value.get('deployment_branch_policy')
         == {'protected_branches': True, 'custom_branch_policies': False},
         'PROTECTED_BRANCH_POLICY_REQUIRED')
    rules = value.get('protection_rules', [])
    reviewers = [r for r in rules if r.get('type') == 'required_reviewers']
    need(len(reviewers) == 1 and reviewers[0].get('prevent_self_review') is True
         and isinstance(reviewers[0].get('reviewers'), list) and reviewers[0]['reviewers'],
         'INDEPENDENT_ENVIRONMENT_REVIEW_REQUIRED')


def sealed_plan(public_keys, run_id):
    """Only a privileged cloud bootstrap job calls this; tests use fake keys."""
    from nacl.public import PublicKey, SealedBox
    need(set(public_keys) == set(ENVIRONMENTS) and run_id.isdigit(), 'KEY_RECIPIENT_SCOPE_INVALID')
    source, writer = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    aes = os.urandom(32)
    key_id = 'GITHUB_' + run_id + '_' + os.urandom(16).hex().upper()
    private = lambda key: b64(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))
    source_public = b64(source.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    writer_public = b64(writer.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    payloads = {'source': {'SOURCE': private(source)}, 'writer': {'WRITER': private(writer), 'AES256': b64(aes)},
                'restore': {'AES256': b64(aes)}, 'drive': {'AES256': b64(aes)}}
    result = {}
    for role, values in payloads.items():
        public = public_keys[role]
        need(set(public) == {'key', 'key_id'} and isinstance(public['key_id'], str)
             and re.fullmatch(r'[A-Za-z0-9_-]{1,200}', public['key_id']), 'GITHUB_PUBLIC_KEY_INVALID')
        box = SealedBox(PublicKey(unb64(public['key'], 32)))
        secrets, variables = {}, {'DR_D1_BACKUP_KEY_ID': key_id,
            'DR_D1_BACKUP_SOURCE_PUBLIC_KEY': source_public, 'DR_D1_BACKUP_WRITER_PUBLIC_KEY': writer_public}
        for kind, raw in values.items():
            name = f'DR_D1_BACKUP_{kind}_{key_id}'
            secrets[name] = {'key_id': public['key_id'], 'encrypted_value': b64(box.encrypt(raw.encode()))}
            variables[f'DR_D1_BACKUP_{kind}_SECRET_NAME'] = name
        if role != 'source':
            variables['DR_D1_BACKUP_AES256_SHA256'] = sha(aes)
        result[role] = {'secrets': secrets, 'variables': variables}
    return result, {'key_id': key_id, 'source_public_key': source_public,
        'writer_public_key': writer_public, 'aes256_sha256': sha(aes)}


class GitHubEnvironments:
    def __init__(self, token, client=None):
        self.client = client or httpx.Client(follow_redirects=False, timeout=20)
        self.token = token

    def call(self, method, environment, suffix='', body=None):
        need(environment in {*ENVIRONMENTS.values(), PROVISION_ENVIRONMENT}, 'KEY_ENVIRONMENT_NOT_ALLOWED')
        allowed = (method == 'GET' and suffix in {'', '/secrets/public-key', '/variables?per_page=100'}) or (
            method == 'POST' and suffix == '/variables') or (
            method == 'PUT' and re.fullmatch(r'/secrets/DR_D1_BACKUP_(SOURCE|WRITER|AES256)_GITHUB_[0-9]+_[A-F0-9]{32}', suffix))
        need(allowed, 'KEY_API_OPERATION_NOT_ALLOWED')
        need(bool(self.token) or (method == 'GET' and suffix == ''), 'APPROVED_ENVIRONMENT_WRITE_CREDENTIAL_REQUIRED')
        url = f'https://api.github.com/repos/{REPO}/environments/{quote(environment, safe="")}{suffix}'
        headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        # POST is create-only for variables. A 204 secret upsert indicates an
        # unexpected collision and stops the run; approved references never PATCH.
        with self.client.stream(method, url, json=body, headers=headers) as response:
            need(response.status_code == (200 if method == 'GET' else 201), 'KEY_API_FAILED_OR_CONFLICT')
            if method != 'GET':
                return None
            data = bytearray()
            for chunk in response.iter_bytes(65536):
                need(len(data) + len(chunk) <= 256_000, 'KEY_API_RESPONSE_BOUND')
                data.extend(chunk)
            return json.loads(data)

    def preflight(self):
        for name in [PROVISION_ENVIRONMENT, *ENVIRONMENTS.values()]:
            protected_environment(self.call('GET', name), name)
        return {'status': 'KEY_ENVIRONMENT_PROTECTIONS_VERIFIED', 'environments': 5}

    def provision(self, run_id):
        need(bool(self.token), 'APPROVED_ENVIRONMENT_WRITE_CREDENTIAL_REQUIRED')
        self.preflight()
        public_keys = {}
        # Every environment is inspected BEFORE any key generation or mutation.
        for role, name in ENVIRONMENTS.items():
            protected_environment(self.call('GET', name), name)
            current = self.call('GET', name, '/variables?per_page=100')
            need(type(current.get('total_count')) is int and current['total_count'] <= 100,
                 'KEY_VARIABLE_INVENTORY_BOUND')
            values = current.get('variables')
            need(isinstance(values, list) and len(values) == current['total_count']
                 and not any(v.get('name') in REFERENCE_NAMES for v in values),
                 'EXISTING_KEY_REFERENCES_REQUIRE_REVIEW_NOT_ROTATION')
            public_keys[role] = self.call('GET', name, '/secrets/public-key')
        plan, receipt = sealed_plan(public_keys, run_id)
        # Unique 128-bit-suffixed secret names avoid touching existing keys.
        # Cross-environment publication is not transactional: failures remain
        # PARTIAL, never auto-rotated/repaired or certified as recoverable.
        for role, name in ENVIRONMENTS.items():
            protected_environment(self.call('GET', name), name)
            for secret, encrypted in plan[role]['secrets'].items():
                self.call('PUT', name, '/secrets/' + secret, encrypted)
            for variable, value in plan[role]['variables'].items():
                self.call('POST', name, '/variables', {'name': variable, 'value': value})
        return receipt | {'status': 'CLOUD_KEYS_PUBLISHED_INDEPENDENT_READBACK_REQUIRED'}


def verify_recipient(role, env):
    need(role in ENVIRONMENTS, 'UNKNOWN_KEY_ROLE')
    need(env.get('DR_D1_BACKUP_KEY_ID') == env.get('EXPECTED_KEY_ID'), 'KEYSET_ID_MISMATCH')
    if role in {'source', 'writer'}:
        key = Ed25519PrivateKey.from_private_bytes(unb64(env['PRIVATE_KEY'], 32))
        public = b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
        need(public == env['EXPECTED_PUBLIC_KEY'], 'STORED_SIGNING_KEY_MISMATCH')
    if role != 'source':
        need(sha(unb64(env['AES256_KEY'], 32)) == env['EXPECTED_AES256_SHA256'], 'STORED_AES256_KEY_MISMATCH')
    return {'status': 'CLOUD_KEY_RECIPIENT_VERIFIED', 'role': role, 'key_id': env['EXPECTED_KEY_ID']}


def main():
    try:
        require_cloud(os.environ)
        need(os.environ.get('DR_D1_KEY_BOOTSTRAP_APPROVED_SHA') == os.environ.get('GITHUB_SHA')
             and os.environ.get('DR_D1_KEY_BOOTSTRAP_APPROVED_RUN_ID') == os.environ.get('GITHUB_RUN_ID'),
             'EXACT_KEY_BOOTSTRAP_APPROVAL_REQUIRED')
        role = os.environ.get('DR_D1_KEY_VERIFY_ROLE')
        if os.environ.get('DR_D1_KEY_PREFLIGHT_ONLY') == 'true':
            result = GitHubEnvironments('').preflight()
        elif role:
            result = verify_recipient(role, os.environ)
        else:
            result = GitHubEnvironments(os.environ['DR_D1_KEY_PROVISION_TOKEN']).provision(os.environ['GITHUB_RUN_ID'])
            output = os.environ.get('GITHUB_OUTPUT')
            need(bool(output), 'CLOUD_STEP_OUTPUT_REQUIRED')
            with open(output, 'a', encoding='utf-8') as stream:
                for key, value in result.items():
                    # Only public keys/key fingerprints/status; NEVER private keys.
                    stream.write(f'{key}={value}\n')
        print(json.dumps(result, sort_keys=True))
    except Exception:
        raise SystemExit('Cloud key provisioning/readback INCOMPLETE; preserve existing keys and inspect protected metadata') from None


if __name__ == '__main__':
    main()
