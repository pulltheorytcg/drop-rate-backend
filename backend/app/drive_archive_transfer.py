"""Private, bounded R2 archive transport and append-only Drive copy receipts.

This module has no Google credential, database connection, URL signer, cleanup,
or arbitrary-key API. Only members of recognised immutable archive manifests
can be transferred. The caller is the separately authenticated n8n bridge.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import time

from .catalogue_source_archives import (
    CHECKPOINT as SOURCE_CHECKPOINT, INPUTS as SOURCE_INPUTS,
    SCHEMA as SOURCE_SCHEMA, SOURCE_COMMIT,
)
from .object_storage import ObjectStorageConfig, ObjectStorageError
from .reference_history_archive import FORMAT as HISTORY_SCHEMA

EXPECTED_ACCOUNT = 'dropratetcg@gmail.com'
EXPECTED_FOLDER = '1NhFIsWesgxlf059UMdx65ps9kFMqQeO9'
EXPECTED_FOLDER_NAME = 'Drop Rate - Pricing History Archives'
KINDS = ('REFERENCE_HISTORY', 'OPENLIBRARY_REVIEWED')
MAX_OBJECT_BYTES = 16_000_000
MAX_MANIFEST_BYTES = 256_000
MAX_RECORD_BYTES = 64_000
MAX_LIST_KEYS = 40
MAX_MEMBERS = 16
CHUNK_BYTES = 64 * 1024
TRANSFER_SECONDS = 60
DESTINATION_ID = hashlib.sha256((EXPECTED_ACCOUNT + '\0' + EXPECTED_FOLDER).encode()).hexdigest()
SHA = re.compile(r'^[a-f0-9]{64}$')
DRIVE_ID = re.compile(r'^[A-Za-z0-9_-]{10,200}$')
_storage_slots = threading.BoundedSemaphore(2)


class ArchiveTransferError(ObjectStorageError):
    """A fixed public error code; never include provider exceptions or URLs."""


class UnrecognisedArchive(ArchiveTransferError):
    pass


def require(value, code):
    if not value:
        raise ArchiveTransferError(code)


def digest(value):
    require(isinstance(value, str) and SHA.fullmatch(value) is not None, 'INVALID_DIGEST')
    return value


def object_size(value):
    require(type(value) is int and value > 0,'OBJECT_SIZE_INVALID')
    if value > MAX_OBJECT_BYTES:
        error = ArchiveTransferError('OBJECT_TOO_LARGE')
        error.declared_size_bytes = value
        raise error
    return value


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def _no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'DUPLICATE_JSON_FIELD')
        value[key] = item
    return value


def decode_json(data):
    try:
        value = json.loads(data, object_pairs_hook=_no_duplicates,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        require(isinstance(value, dict), 'INVALID_JSON_OBJECT')
        return value
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise ArchiveTransferError('INVALID_JSON_OBJECT') from exc


def _timestamp(value):
    if isinstance(value, datetime):
        stamp = value
    else:
        try:
            stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, TypeError) as exc:
            raise ArchiveTransferError('INVALID_TIMESTAMP') from exc
    require(stamp.tzinfo is not None and stamp.utcoffset() is not None, 'INVALID_TIMESTAMP')
    return stamp.astimezone(timezone.utc)


def validate_destination(value, *, now=None):
    """Validate signed evidence obtained by the workflow's actual OAuth reads.

    This binds the intended account/folder; it is not a substitute for the
    workflow's Google about/files calls and does not claim backend Google auth.
    """
    expected = {'account_email', 'account_permission_id', 'folder_id', 'folder_name',
                'folder_mime_type', 'folder_trashed', 'folder_shared', 'folder_owner_email',
                'folder_owner_permission_id', 'permission_roles', 'checked_at'}
    require(isinstance(value, dict) and set(value) == expected, 'INVALID_DESTINATION_EVIDENCE')
    require(value['account_email'] == EXPECTED_ACCOUNT
            and value['folder_owner_email'] == EXPECTED_ACCOUNT
            and value['folder_id'] == EXPECTED_FOLDER
            and value['folder_name'] == EXPECTED_FOLDER_NAME
            and value['folder_mime_type'] == 'application/vnd.google-apps.folder'
            and value['folder_trashed'] is False and value['folder_shared'] is False
            and value['permission_roles'] == ['owner'], 'DESTINATION_MISMATCH')
    permission = value['account_permission_id']
    require(isinstance(permission, str) and 1 <= len(permission) <= 200
            and permission == value['folder_owner_permission_id'], 'DESTINATION_OWNER_MISMATCH')
    stamp = _timestamp(value['checked_at'])
    now = now or datetime.now(timezone.utc)
    require(abs((now - stamp).total_seconds()) <= 300, 'DESTINATION_EVIDENCE_STALE')
    return permission


@dataclass(frozen=True)
class ArchiveMember:
    sha256: str
    size_bytes: int
    key: str
    suffix: str
    mime_type: str
    role: str
    raw_sha256: str | None = None
    raw_size_bytes: int | None = None

    def public(self, kind):
        return {'sha256': self.sha256, 'size_bytes': self.size_bytes,
                'file_name': f'drop-rate-{kind.lower()}-{self.sha256}{self.suffix}',
                'mime_type': self.mime_type, 'role': self.role}


@dataclass(frozen=True)
class ArchiveBundle:
    kind: str
    manifest_sha256: str
    archive_id: str
    content_root_sha256: str
    members: tuple[ArchiveMember, ...]

    def member(self, sha256):
        digest(sha256)
        found = [item for item in self.members if item.sha256 == sha256]
        require(len(found) == 1, 'OBJECT_NOT_IN_ARCHIVE')
        return found[0]


@dataclass
class StagedObject:
    directory: tempfile.TemporaryDirectory
    path: Path
    member: ArchiveMember
    file_name: str

    def cleanup(self):
        self.directory.cleanup()


async def storage_call(function, *args, **kwargs):
    """Bound running SDK threads even when the waiting request times out."""
    require(_storage_slots.acquire(blocking=False), 'TRANSFER_BUSY')

    def run():
        try:
            return function(*args, **kwargs)
        finally:
            _storage_slots.release()

    try:
        try:
            future = asyncio.get_running_loop().run_in_executor(None,run)
        except BaseException:
            _storage_slots.release()
            raise
        # Keep the submitted worker alive after caller cancellation, so its
        # finally block always releases the bounded slot.
        future.add_done_callback(lambda result: result.exception() if not result.cancelled() else None)
        return await asyncio.wait_for(asyncio.shield(future), TRANSFER_SECONDS + 20)
    except TimeoutError as exc:
        raise ArchiveTransferError('TRANSFER_TIMEOUT') from exc


class ArchiveTransfer:
    def __init__(self, config, client=None):
        self.config = config
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client('s3', endpoint_url=config.endpoint,
                region_name=config.region, aws_access_key_id=config.access_key_id,
                aws_secret_access_key=config.secret_access_key,
                config=Config(signature_version='s3v4', connect_timeout=3,
                              read_timeout=15, retries={'max_attempts': 1}))
        self.client = client

    @classmethod
    def configured(cls):
        config = ObjectStorageConfig.from_env()
        require(config is not None, 'PRIVATE_STORAGE_UNAVAILABLE')
        return cls(config)

    def _prefix(self, kind):
        require(kind in KINDS, 'UNSUPPORTED_ARCHIVE_KIND')
        category = 'reference-history' if kind == 'REFERENCE_HISTORY' else 'exports'
        return f'{self.config.prefix}/{category}/'

    @staticmethod
    def _error_code(exc):
        response = getattr(exc, 'response', {})
        return str(response.get('Error', {}).get('Code', '')) if isinstance(response, dict) else ''

    def _read(self, key, maximum, *, expected_sha=None, expected_size=None, output=None):
        deadline = time.monotonic() + TRANSFER_SECONDS
        try:
            response = self.client.get_object(Bucket=self.config.bucket, Key=key)
            body = response['Body']
            data = bytearray() if output is None else None
            sha, size = hashlib.sha256(), 0
            try:
                length = response.get('ContentLength')
                require(type(length) is int and 0 < length <= maximum, 'OBJECT_SIZE_INVALID')
                if expected_size is not None:
                    require(length == expected_size, 'OBJECT_SIZE_MISMATCH')
                while True:
                    require(time.monotonic() <= deadline, 'TRANSFER_TIMEOUT')
                    chunk = body.read(min(CHUNK_BYTES, maximum - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    require(size <= maximum, 'OBJECT_TOO_LARGE')
                    sha.update(chunk)
                    if output is None:
                        data.extend(chunk)
                    else:
                        output.write(chunk)
            finally:
                body.close()
            require(size == length and (expected_size is None or size == expected_size), 'OBJECT_SIZE_MISMATCH')
            require(expected_sha is None or sha.hexdigest() == expected_sha, 'OBJECT_SHA_MISMATCH')
            return bytes(data) if data is not None else None
        except ArchiveTransferError:
            raise
        except Exception as exc:
            if self._error_code(exc) in {'NoSuchKey', '404', 'NotFound'}:
                raise ArchiveTransferError('OBJECT_NOT_FOUND') from exc
            raise ArchiveTransferError('PRIVATE_STORAGE_READ_FAILED') from exc

    def load_archive(self, kind, manifest_sha256):
        digest(manifest_sha256)
        prefix = self._prefix(kind)
        key = prefix + manifest_sha256 + '.manifest.json'
        try:
            data = self._read(key, MAX_MANIFEST_BYTES, expected_sha=manifest_sha256)
        except ArchiveTransferError as exc:
            if str(exc) != 'OBJECT_NOT_FOUND' or kind != 'REFERENCE_HISTORY':
                raise
            key = prefix + manifest_sha256 + '.json'
            data = self._read(key, MAX_MANIFEST_BYTES, expected_sha=manifest_sha256)
        manifest = decode_json(data)
        schema = HISTORY_SCHEMA if kind == 'REFERENCE_HISTORY' else SOURCE_SCHEMA
        if manifest.get('schema') != schema:
            raise UnrecognisedArchive('UNRECOGNISED_ARCHIVE_SCHEMA')
        digest(manifest.get('content_root_sha256'))
        if kind == 'REFERENCE_HISTORY':
            required = {'schema','row_count','raw_bytes','ndjson_sha256','content_root_sha256',
                        'gzip_sha256','gzip_bytes','full_table_snapshot','archive_object',
                        'restoration_verified','storage_endpoint','storage_bucket','restoration_method'}
            require(set(manifest) == required and manifest['full_table_snapshot'] is True
                and manifest['restoration_verified'] is True
                and manifest['restoration_method'] == 'POSTGRES_TEMP_TABLE_EVERY_FIELD_V1',
                'HISTORY_RESTORE_PROOF_MISSING')
            require(type(manifest['row_count']) is int and 1 <= manifest['row_count'] <= 100_000
                and type(manifest['raw_bytes']) is int and 1 <= manifest['raw_bytes'] <= 128_000_000,
                'HISTORY_BOUNDS_INVALID')
            require(isinstance(manifest['storage_endpoint'],str)
                and manifest['storage_endpoint'].rstrip('/') == self.config.endpoint.rstrip('/')
                and manifest['storage_bucket'] == self.config.bucket, 'HISTORY_STORAGE_MISMATCH')
            digest(manifest['ndjson_sha256'])
            digest(manifest['gzip_sha256'])
            size = object_size(manifest['gzip_bytes'])
            object_key = prefix + manifest['gzip_sha256'] + '.ndjson.gz'
            expected = {'key': object_key, 'sha256': manifest['gzip_sha256'],
                        'size_bytes': size, 'verified': True}
            require(manifest['archive_object'] == expected, 'HISTORY_OBJECT_MISMATCH')
            members = [ArchiveMember(manifest['gzip_sha256'], size, object_key,
                                     '.ndjson.gz', 'application/gzip', 'HISTORY')]
            archive_id = 'r2-reference-history-' + manifest['content_root_sha256']
        else:
            require(manifest.get('checkpoint') == SOURCE_CHECKPOINT
                and manifest.get('source_commit') == SOURCE_COMMIT
                and manifest.get('source') == 'OPEN_LIBRARY'
                and manifest.get('contains_original_dump') is False
                and manifest.get('contains_cover_bytes') is False
                and manifest.get('archive_grants_publication_rights') is False,
                'SOURCE_CHECKPOINT_MISMATCH')
            files = manifest.get('files')
            require(isinstance(files, list) and len(files) == len(SOURCE_INPUTS), 'SOURCE_MEMBERS_MISMATCH')
            members = []
            identities = []
            for actual, expected in zip(files, SOURCE_INPUTS):
                require(isinstance(actual, dict) and set(actual) == {
                    'path','role','sha256','size_bytes','gzip_sha256','gzip_bytes','object'},
                    'SOURCE_MEMBER_SCHEMA_MISMATCH')
                identity = {field: actual[field] for field in ('path','role','sha256','size_bytes')}
                require(identity == {field: getattr(expected, field) for field in identity},
                        'SOURCE_MEMBER_NOT_REVIEWED')
                identities.append(identity)
                sha = digest(actual['gzip_sha256'])
                size = object_size(actual['gzip_bytes'])
                suffix = Path(expected.path).suffix + '.gz'
                object_key = prefix + sha + suffix
                require(actual['object'] == {'key':object_key,'sha256':sha,'size_bytes':size,'verified':True},
                        'SOURCE_OBJECT_MISMATCH')
                members.append(ArchiveMember(sha,size,object_key,suffix,'application/gzip',expected.role,
                                             expected.sha256,expected.size_bytes))
            require(hashlib.sha256(canonical_json(identities)).hexdigest() == manifest['content_root_sha256'],
                    'SOURCE_CONTENT_ROOT_MISMATCH')
            archive_id = SOURCE_CHECKPOINT + ':' + manifest['content_root_sha256']
        members.append(ArchiveMember(manifest_sha256,len(data),key,'.manifest.json','application/json','MANIFEST'))
        require(1 < len(members) <= MAX_MEMBERS
                and len({item.sha256 for item in members}) == len(members), 'ARCHIVE_MEMBERS_INVALID')
        return ArchiveBundle(kind,manifest_sha256,archive_id,manifest['content_root_sha256'],tuple(members))

    def _record_key(self, bundle, category, object_sha256=None):
        require(category in {'reservations','objects','complete'}, 'INVALID_RECORD_CATEGORY')
        suffix = digest(object_sha256) if object_sha256 is not None else 'complete'
        return (f'{self.config.prefix}/drive-archive-copy/v1/{DESTINATION_ID}/{category}/'
                f'{bundle.kind}/{bundle.manifest_sha256}/{suffix}.json')

    def _record(self, key):
        try:
            return decode_json(self._read(key, MAX_RECORD_BYTES))
        except ArchiveTransferError as exc:
            if str(exc) == 'OBJECT_NOT_FOUND':
                return None
            raise

    def _create_once(self, key, value):
        data = canonical_json(value)
        require(0 < len(data) <= MAX_RECORD_BYTES, 'RECORD_TOO_LARGE')
        created = True
        try:
            self.client.put_object(Bucket=self.config.bucket,Key=key,Body=io.BytesIO(data),
                ContentType='application/json',CacheControl='no-store',IfNoneMatch='*',
                Metadata={'sha256':hashlib.sha256(data).hexdigest()})
        except Exception as exc:
            if self._error_code(exc) not in {'PreconditionFailed','412','ConditionalRequestConflict','409'}:
                raise ArchiveTransferError('PRIVATE_STORAGE_WRITE_FAILED') from exc
            created = False
        actual = self._read(key,MAX_RECORD_BYTES)
        require(not created or actual == data, 'RECORD_READBACK_MISMATCH')
        return decode_json(actual)

    @staticmethod
    def _identity(bundle, member=None):
        value = {'destination_id':DESTINATION_ID,'kind':bundle.kind,
                 'manifest_sha256':bundle.manifest_sha256,'archive_id':bundle.archive_id,
                 'folder_id':EXPECTED_FOLDER,'account_email':EXPECTED_ACCOUNT}
        if member is not None:
            value.update(object_sha256=member.sha256,size_bytes=member.size_bytes)
        return value

    def _validate_record_identity(self, value, bundle, member=None):
        require(isinstance(value, dict) and all(value.get(key) == item
            for key,item in self._identity(bundle,member).items()), 'RECORD_IDENTITY_MISMATCH')

    def reservation(self, bundle, member):
        value = self._record(self._record_key(bundle,'reservations',member.sha256))
        if value is not None:
            self._validate_record_identity(value,bundle,member)
            require(value.get('schema') == 'drop-rate-drive-file-reservation-v1'
                    and isinstance(value.get('file_id'),str) and DRIVE_ID.fullmatch(value['file_id'])
                    and value.get('file_name') == member.public(bundle.kind)['file_name']
                    and value.get('app_properties') == self.app_properties(bundle,member),
                    'RESERVATION_INVALID')
        return value

    @staticmethod
    def app_properties(bundle, member):
        return {'drSchema':'drive-copy-v1','drKind':bundle.kind,
                'drManifest':bundle.manifest_sha256,'drObject':member.sha256}

    def reserve(self, bundle, member, proposed_file_id):
        require(isinstance(proposed_file_id,str) and DRIVE_ID.fullmatch(proposed_file_id), 'INVALID_DRIVE_FILE_ID')
        existing = self.reservation(bundle,member)
        if existing is None:
            record = dict(schema='drop-rate-drive-file-reservation-v1',**self._identity(bundle,member),
                file_id=proposed_file_id,file_name=member.public(bundle.kind)['file_name'],
                app_properties=self.app_properties(bundle,member))
            self._create_once(self._record_key(bundle,'reservations',member.sha256),record)
            existing = self.reservation(bundle,member)
        return {key:existing[key] for key in ('file_id','file_name','app_properties')}

    def stage(self, bundle, member):
        directory = tempfile.TemporaryDirectory(prefix='drop-rate-drive-copy-')
        path = Path(directory.name) / 'object.bin'
        try:
            with path.open('xb') as output:
                self._read(member.key,MAX_OBJECT_BYTES,expected_sha=member.sha256,
                           expected_size=member.size_bytes,output=output)
            if member.raw_sha256 is not None:
                sha, size = hashlib.sha256(), 0
                try:
                    with gzip.open(path,'rb') as source:
                        while True:
                            chunk = source.read(min(CHUNK_BYTES,member.raw_size_bytes-size+1))
                            if not chunk:
                                break
                            size += len(chunk)
                            require(size <= member.raw_size_bytes,'SOURCE_RAW_SIZE_MISMATCH')
                            sha.update(chunk)
                except (OSError,EOFError) as exc:
                    raise ArchiveTransferError('SOURCE_GZIP_INVALID') from exc
                require(size == member.raw_size_bytes and sha.hexdigest() == member.raw_sha256,
                        'SOURCE_RAW_SHA_MISMATCH')
            return StagedObject(directory,path,member,member.public(bundle.kind)['file_name'])
        except BaseException:
            directory.cleanup()
            raise

    def validate_drive_file(self, bundle, member, value, account_permission_id):
        reservation = self.reservation(bundle,member)
        require(reservation is not None,'FILE_ID_NOT_RESERVED')
        require(isinstance(value,dict) and set(value) == {
            'id','name','parents','owner_email','owner_permission_id','shared','trashed',
            'mime_type','size_bytes','app_properties'}, 'INVALID_DRIVE_FILE_EVIDENCE')
        require(value['id'] == reservation['file_id'] and value['name'] == reservation['file_name']
            and value['parents'] == [EXPECTED_FOLDER] and value['owner_email'] == EXPECTED_ACCOUNT
            and value['owner_permission_id'] == account_permission_id
            and value['shared'] is False and value['trashed'] is False
            and value['mime_type'] == member.mime_type and type(value['size_bytes']) is int
            and value['size_bytes'] == member.size_bytes
            and value['app_properties'] == reservation['app_properties'], 'DRIVE_FILE_MISMATCH')
        return reservation

    def record_verified_bytes(self, bundle, member, drive_file, *, actual_sha256, actual_size,
                              execution_id, account_permission_id):
        self.validate_drive_file(bundle,member,drive_file,account_permission_id)
        require(actual_sha256 == member.sha256 and actual_size == member.size_bytes,
                'DRIVE_READBACK_MISMATCH')
        record = dict(schema='drop-rate-drive-object-copy-v1',**self._identity(bundle,member),
            file_id=drive_file['id'],file_name=drive_file['name'],
            download_sha256=actual_sha256,download_size_bytes=actual_size,
            verified_at=datetime.now(timezone.utc).isoformat(),execution_id=execution_id,
            verification_method='BACKEND_SHA256_OF_N8N_DRIVE_DOWNLOAD_V1')
        actual = self._create_once(self._record_key(bundle,'objects',member.sha256),record)
        self._validate_object_receipt(actual,bundle,member)
        require(actual['file_id'] == drive_file['id'],'DRIVE_RECEIPT_FILE_MISMATCH')
        return {'status':'BYTES_VERIFIED','file_id':actual['file_id'],
                'object_sha256':member.sha256,'size_bytes':member.size_bytes,
                'verified_at':actual['verified_at'],
                'receipt_sha256':hashlib.sha256(canonical_json(actual)).hexdigest()}

    def _validate_object_receipt(self, value, bundle, member):
        self._validate_record_identity(value,bundle,member)
        reservation = self.reservation(bundle,member)
        require(reservation is not None and value.get('schema') == 'drop-rate-drive-object-copy-v1'
            and value.get('file_id') == reservation['file_id']
            and value.get('file_name') == reservation['file_name']
            and value.get('download_sha256') == member.sha256
            and value.get('download_size_bytes') == member.size_bytes
            and value.get('verification_method') == 'BACKEND_SHA256_OF_N8N_DRIVE_DOWNLOAD_V1',
            'OBJECT_RECEIPT_INVALID')
        _timestamp(value.get('verified_at'))

    def completion(self, bundle):
        value = self._record(self._record_key(bundle,'complete'))
        if value is not None:
            self._validate_record_identity(value,bundle)
            expected = {(m.sha256,m.size_bytes) for m in bundle.members}
            members = value.get('members')
            require(value.get('schema') == 'drop-rate-drive-archive-copy-v1'
                and value.get('content_root_sha256') == bundle.content_root_sha256
                and value.get('history_cleanup_authorised') is False
                and isinstance(members,list) and len(members) == len(expected)
                and {(m.get('object_sha256'),m.get('size_bytes')) for m in members
                     if isinstance(m,dict)} == expected, 'ARCHIVE_RECEIPT_INVALID')
            for member in members:
                require(isinstance(member.get('file_id'),str) and DRIVE_ID.fullmatch(member['file_id']),
                        'ARCHIVE_RECEIPT_INVALID')
                digest(member.get('receipt_sha256'))
                _timestamp(member.get('verified_at'))
            _timestamp(value.get('completed_at'))
        return value

    def complete(self, bundle, execution_id):
        completed = self.completion(bundle)
        if completed is None:
            members = []
            for member in bundle.members:
                receipt = self._record(self._record_key(bundle,'objects',member.sha256))
                require(receipt is not None,'ARCHIVE_COPY_INCOMPLETE')
                self._validate_object_receipt(receipt,bundle,member)
                members.append({'object_sha256':member.sha256,'size_bytes':member.size_bytes,
                    'file_id':receipt['file_id'],'verified_at':receipt['verified_at'],
                    'receipt_sha256':hashlib.sha256(canonical_json(receipt)).hexdigest()})
            record = dict(schema='drop-rate-drive-archive-copy-v1',**self._identity(bundle),
                content_root_sha256=bundle.content_root_sha256,members=members,
                completed_at=datetime.now(timezone.utc).isoformat(),execution_id=execution_id,
                history_cleanup_authorised=False)
            self._create_once(self._record_key(bundle,'complete'),record)
            completed = self.completion(bundle)
        return {'status':'ARCHIVE_COPY_RECORDED','archive_id':bundle.archive_id,
                'manifest_sha256':bundle.manifest_sha256,'objects_verified':len(bundle.members),
                'completed_at':completed['completed_at'],
                'receipt_sha256':hashlib.sha256(canonical_json(completed)).hexdigest(),
                'history_cleanup_authorised':False}

    def plan(self, kind, *, cursor=None, limit=2):
        prefix = self._prefix(kind)
        require(type(limit) is int and 1 <= limit <= 2,'INVALID_PLAN_LIMIT')
        after = None
        if cursor is not None:
            require(isinstance(cursor,str) and len(cursor) <= 1500,'INVALID_PLAN_CURSOR')
            match = re.fullmatch(r'v1\.([01])\.([A-Za-z0-9_-]+)',cursor)
            require(match is not None and int(match[1]) == KINDS.index(kind),'INVALID_PLAN_CURSOR')
            try:
                raw = base64.urlsafe_b64decode(match[2] + '=' * (-len(match[2]) % 4))
                require(0 < len(raw) <= 1024 and base64.urlsafe_b64encode(raw).decode().rstrip('=') == match[2],
                        'INVALID_PLAN_CURSOR')
                after = raw.decode('utf-8')
            except (UnicodeError,ValueError) as exc:
                raise ArchiveTransferError('INVALID_PLAN_CURSOR') from exc
        arguments = dict(Bucket=self.config.bucket,Prefix=prefix,MaxKeys=MAX_LIST_KEYS)
        if after is not None:
            # This cursor controls a listing only. It is never an object-read
            # capability, and its fixed kind prefix cannot select another area.
            arguments['StartAfter'] = prefix + after
        try:
            response = self.client.list_objects_v2(**arguments)
        except Exception as exc:
            raise ArchiveTransferError('PRIVATE_STORAGE_LIST_FAILED') from exc
        contents = response.get('Contents',[])
        require(isinstance(contents,list) and len(contents) <= MAX_LIST_KEYS,'INVALID_STORAGE_LIST')
        archives, blocked, last = [], [], after
        processed = 0
        for entry in contents:
            key = entry.get('Key')
            require(isinstance(key,str) and key.startswith(prefix),'INVALID_STORAGE_LIST')
            basename = key[len(prefix):]
            require(len(basename.encode('utf-8')) <= 1024,'INVALID_STORAGE_LIST')
            last = basename
            processed += 1
            if not (re.fullmatch(r'[a-f0-9]{64}\.manifest\.json',basename) or
                    (kind == 'REFERENCE_HISTORY' and re.fullmatch(r'[a-f0-9]{64}\.json',basename))):
                continue
            sha = basename.split('.')[0]
            try:
                bundle = self.load_archive(kind,sha)
                # A legacy .json and canonical .manifest.json may coexist.
                # Count only the exact preferred manifest selected by loader.
                if bundle.members[-1].key != key:
                    continue
                completed = self.completion(bundle)
            except UnrecognisedArchive:
                if kind == 'REFERENCE_HISTORY':
                    blocked.append({'manifest_sha256':sha,'reason':'UNRECOGNISED_ARCHIVE_SCHEMA'})
                continue
            except ArchiveTransferError as exc:
                issue = {'manifest_sha256':sha,'reason':str(exc)}
                declared = getattr(exc,'declared_size_bytes',None)
                if type(declared) is int:
                    issue.update(declared_size_bytes=declared,maximum_object_bytes=MAX_OBJECT_BYTES)
                blocked.append(issue)
                continue
            archives.append({'kind':kind,'manifest_sha256':sha,'archive_id':bundle.archive_id,
                'copy_status':'RECORDED_BYTES_VERIFIED' if completed else 'PENDING',
                'last_recorded_verification_at':completed['completed_at'] if completed else None,
                'objects':[member.public(kind) for member in bundle.members]})
            if len(archives) == limit:
                break
        more = processed < len(contents) or response.get('IsTruncated') is True
        require(not more or (isinstance(last,str) and last),'INVALID_STORAGE_PAGINATION')
        next_cursor = ('v1.' + str(KINDS.index(kind)) + '.'
                       + base64.urlsafe_b64encode(last.encode()).decode().rstrip('=')) if more else None
        return {'archives':archives,'blocked_archives':blocked,'has_more':more,
                'next_cursor':next_cursor,'scan_scope':'PAGE',
                'drive_current_availability':'NOT_ASSESSED',
                'history_cleanup_authorised':False}
