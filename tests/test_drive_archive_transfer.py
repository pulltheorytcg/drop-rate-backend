"""Synthetic-bucket tests; no Drive/R2 network, credentials, or database writes."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timezone
import gzip
import hashlib
import io
import threading

import pytest

from app import drive_archive_transfer as transfer
from app.catalogue_source_archives import SourceInput
from app.object_storage import ObjectStorageConfig, S3ObjectStorage


class StorageFailure(Exception):
    def __init__(self, code):
        self.response = {'Error':{'Code':code}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.lock = threading.Lock()
        self.corrupt_writes = False

    def get_object(self, *, Bucket, Key):
        self.calls.append(('get',Key))
        if Key not in self.objects:
            raise StorageFailure('NoSuchKey')
        data = self.objects[Key]
        return {'Body':io.BytesIO(data),'ContentLength':len(data)}

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch=None, **_kwargs):
        if '/drive-archive-copy/' in Key:
            assert IfNoneMatch == '*', 'Copy control records must never overwrite'
        data = Body.read()
        with self.lock:
            self.calls.append(('put',Key))
            if Key in self.objects and IfNoneMatch == '*':
                raise StorageFailure('PreconditionFailed')
            self.objects[Key] = data + b'corrupt' if self.corrupt_writes else data

    def list_objects_v2(self, *, Bucket, Prefix, MaxKeys, StartAfter=''):
        self.calls.append(('list',Prefix))
        keys = sorted(key for key in self.objects if key.startswith(Prefix) and key > StartAfter)
        return {'Contents':[{'Key':key,'Size':len(self.objects[key])} for key in keys[:MaxKeys]],
                'IsTruncated':len(keys) > MaxKeys}


def destination():
    return {'account_email':transfer.EXPECTED_ACCOUNT,'account_permission_id':'owner-permission-1',
        'folder_id':transfer.EXPECTED_FOLDER,'folder_name':transfer.EXPECTED_FOLDER_NAME,
        'folder_mime_type':'application/vnd.google-apps.folder','folder_trashed':False,
        'folder_shared':False,'folder_owner_email':transfer.EXPECTED_ACCOUNT,
        'folder_owner_permission_id':'owner-permission-1','permission_roles':['owner'],
        'checked_at':datetime.now(timezone.utc).isoformat()}


def drive_metadata(bundle, member, reservation):
    return {'id':reservation['file_id'],'name':reservation['file_name'],
        'parents':[transfer.EXPECTED_FOLDER],'owner_email':transfer.EXPECTED_ACCOUNT,
        'owner_permission_id':'owner-permission-1','shared':False,'trashed':False,
        'mime_type':member.mime_type,'size_bytes':member.size_bytes,
        'app_properties':reservation['app_properties']}


def history_fixture(service, raw=b'{"synthetic":"history-one"}\n', change=None):
    data = gzip.compress(raw,mtime=0)
    sha = hashlib.sha256(data).hexdigest()
    key = f'{service.config.prefix}/reference-history/{sha}.ndjson.gz'
    manifest = {'schema':transfer.HISTORY_SCHEMA,'row_count':1,'raw_bytes':len(raw),
        'ndjson_sha256':hashlib.sha256(raw).hexdigest(),
        'content_root_sha256':hashlib.sha256(raw[:-1]).hexdigest(),
        'gzip_sha256':sha,'gzip_bytes':len(data),'full_table_snapshot':True,
        'archive_object':{'key':key,'sha256':sha,'size_bytes':len(data),'verified':True},
        'restoration_verified':True,'storage_endpoint':service.config.endpoint,
        'storage_bucket':service.config.bucket,
        'restoration_method':'POSTGRES_TEMP_TABLE_EVERY_FIELD_V1'}
    if change:
        manifest.update(change)
    manifest_bytes = transfer.canonical_json(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    service.client.objects[key] = data
    service.client.objects[f'{service.config.prefix}/reference-history/{manifest_sha}.manifest.json'] = manifest_bytes
    return manifest_sha, manifest, data


@pytest.fixture
def service():
    config = ObjectStorageConfig('https://fixture.invalid','private-test','auto','synthetic-id','synthetic-secret')
    return transfer.ArchiveTransfer(config,FakeS3())


@pytest.fixture
def bundle(service):
    sha,_,_ = history_fixture(service)
    return service.load_archive('REFERENCE_HISTORY',sha)


def record_all(service,bundle):
    for index,member in enumerate(bundle.members):
        reservation = service.reserve(bundle,member,f'drive_file_fixture_{index:03d}')
        service.record_verified_bytes(bundle,member,drive_metadata(bundle,member,reservation),
            actual_sha256=member.sha256,actual_size=member.size_bytes,
            execution_id='test-1',account_permission_id='owner-permission-1')


def test_manifest_transport_is_exact_private_and_bounded(service,bundle):
    for member in bundle.members:
        staged = service.stage(bundle,member)
        path = staged.path
        assert path.read_bytes() == service.client.objects[member.key]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == member.sha256
        staged.cleanup()
        assert not path.exists()
        assert 'key' not in member.public(bundle.kind)
    assert len(bundle.members) == 2
    assert not any(operation == 'put' for operation,_ in service.client.calls)


@pytest.mark.parametrize('change',[
    {'full_table_snapshot':False},{'restoration_verified':False},
    {'restoration_method':'UNVERIFIED_METADATA'}, {'storage_bucket':'another-bucket'},
    {'storage_endpoint':None},{'row_count':True},{'row_count':0},{'raw_bytes':0},
    {'gzip_bytes':transfer.MAX_OBJECT_BYTES+1},{'content_root_sha256':'not-a-digest'},
    {'unexpected':'field'},
])
def test_unverified_or_unbounded_history_is_rejected(service,change):
    sha,_,_ = history_fixture(service,change=change)
    with pytest.raises(transfer.ArchiveTransferError):
        service.load_archive('REFERENCE_HISTORY',sha)


def test_manifest_cannot_point_to_arbitrary_storage_object(service):
    sha,manifest,_ = history_fixture(service)
    manifest['archive_object']['key'] = 'drop-rate/private-media/unrelated.webp'
    data = transfer.canonical_json(manifest)
    changed = hashlib.sha256(data).hexdigest()
    service.client.objects[f'drop-rate/reference-history/{changed}.manifest.json'] = data
    with pytest.raises(transfer.ArchiveTransferError,match='HISTORY_OBJECT_MISMATCH'):
        service.load_archive('REFERENCE_HISTORY',changed)
    for kind in ('private-media','exports','CATALOGUE_CACHE'):
        with pytest.raises(transfer.ArchiveTransferError,match='UNSUPPORTED_ARCHIVE_KIND'):
            service.load_archive(kind,sha)


def test_source_content_changes_and_missing_members_fail(service,bundle):
    member = bundle.members[0]
    service.client.objects[member.key] = b'x' * member.size_bytes
    with pytest.raises(transfer.ArchiveTransferError,match='OBJECT_SHA_MISMATCH'):
        service.stage(bundle,member)
    with pytest.raises(transfer.ArchiveTransferError,match='OBJECT_NOT_IN_ARCHIVE'):
        bundle.member('0' * 64)
    with pytest.raises(transfer.ArchiveTransferError,match='INVALID_DIGEST'):
        bundle.member('https://example.invalid/private')


def test_source_checkpoint_uses_reviewed_raw_pins(service,monkeypatch):
    raw = b'{"reviewed":"factual metadata"}\n'
    pin = SourceInput('backend/app/data/reviewed.json',hashlib.sha256(raw).hexdigest(),len(raw),'REVIEWED_SOURCE')
    monkeypatch.setattr(transfer,'SOURCE_INPUTS',(pin,))
    compressed = gzip.compress(raw,mtime=0)
    gz_sha = hashlib.sha256(compressed).hexdigest()
    identity = {key:getattr(pin,key) for key in ('path','role','sha256','size_bytes')}
    key = f'drop-rate/exports/{gz_sha}.json.gz'
    manifest = {'schema':transfer.SOURCE_SCHEMA,'checkpoint':transfer.SOURCE_CHECKPOINT,
        'source_commit':transfer.SOURCE_COMMIT,'source':'OPEN_LIBRARY',
        'contains_original_dump':False,'contains_cover_bytes':False,'archive_grants_publication_rights':False,
        'content_root_sha256':hashlib.sha256(transfer.canonical_json([identity])).hexdigest(),
        'files':[dict(identity,gzip_sha256=gz_sha,gzip_bytes=len(compressed),
            object={'key':key,'sha256':gz_sha,'size_bytes':len(compressed),'verified':True})]}
    data = transfer.canonical_json(manifest)
    sha = hashlib.sha256(data).hexdigest()
    service.client.objects[key] = compressed
    service.client.objects[f'drop-rate/exports/{sha}.manifest.json'] = data
    bundle = service.load_archive('OPENLIBRARY_REVIEWED',sha)
    staged = service.stage(bundle,bundle.members[0])
    staged.cleanup()
    # Even a manifest that honestly hashes different gzip bytes cannot replace
    # the separately reviewed raw source hash.
    bad_raw = b'{"reviewed":"different bytes!"}\n'
    bad_gz = gzip.compress(bad_raw,mtime=0)
    bad_sha = hashlib.sha256(bad_gz).hexdigest()
    bad_key = f'drop-rate/exports/{bad_sha}.json.gz'
    manifest['files'][0].update(gzip_sha256=bad_sha,gzip_bytes=len(bad_gz),
        object={'key':bad_key,'sha256':bad_sha,'size_bytes':len(bad_gz),'verified':True})
    data = transfer.canonical_json(manifest)
    sha = hashlib.sha256(data).hexdigest()
    service.client.objects[bad_key] = bad_gz
    service.client.objects[f'drop-rate/exports/{sha}.manifest.json'] = data
    bundle = service.load_archive('OPENLIBRARY_REVIEWED',sha)
    with pytest.raises(transfer.ArchiveTransferError,match='SOURCE_RAW_'):
        service.stage(bundle,bundle.members[0])


@pytest.mark.parametrize('change',[
    {'account_email':'other@example.invalid'},{'folder_id':'another-folder'},
    {'folder_shared':True},{'folder_trashed':True},{'permission_roles':['owner','reader']},
    {'folder_owner_email':'another@example.invalid'}, {'folder_owner_permission_id':'other'},
    {'checked_at':'2020-01-01T00:00:00+00:00'}, {'unexpected':'field'},
])
def test_wrong_or_stale_destination_is_rejected(change):
    with pytest.raises(transfer.ArchiveTransferError):
        transfer.validate_destination(destination()|change)


def test_racing_reservations_reuse_one_file_id(service,bundle):
    member = bundle.members[0]
    proposed = ('drive_file_candidate_one','drive_file_candidate_two')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda file_id:service.reserve(bundle,member,file_id),proposed))
    assert results[0] == results[1]
    assert results[0]['file_id'] in proposed
    assert service.reserve(bundle,member,'drive_file_retry_three') == results[0]
    assert len([key for key in service.client.objects if '/reservations/' in key]) == 1


def test_record_write_requires_actual_r2_readback(service,bundle):
    service.client.corrupt_writes = True
    with pytest.raises(transfer.ArchiveTransferError,match='RECORD_READBACK_MISMATCH'):
        service.reserve(bundle,bundle.members[0],'drive_file_candidate_one')


@pytest.mark.parametrize('change',[
    {'id':'unrelated_existing_file'},{'name':'unrelated existing file'},
    {'parents':['another-folder']},{'owner_email':'other@example.invalid'},
    {'owner_permission_id':'another-owner'},{'shared':True},{'trashed':True},
    {'mime_type':'application/vnd.google-apps.document'},{'size_bytes':0},
    {'app_properties':{'drSchema':'different'}},
])
def test_wrong_drive_file_cannot_get_a_copy_receipt(service,bundle,change):
    member = bundle.members[0]
    reservation = service.reserve(bundle,member,'drive_file_candidate_one')
    metadata = drive_metadata(bundle,member,reservation)|change
    with pytest.raises(transfer.ArchiveTransferError,match='DRIVE_FILE_MISMATCH'):
        service.record_verified_bytes(bundle,member,metadata,
            actual_sha256=member.sha256,actual_size=member.size_bytes,
            execution_id='test-1',account_permission_id='owner-permission-1')
    assert not any('/objects/' in key for key in service.client.objects)


def test_listing_or_partial_copy_never_creates_archive_success(service,bundle):
    page = service.plan('REFERENCE_HISTORY')
    assert page['archives'][0]['copy_status'] == 'PENDING'
    assert page['drive_current_availability'] == 'NOT_ASSESSED'
    assert page['scan_scope'] == 'PAGE'
    with pytest.raises(transfer.ArchiveTransferError,match='ARCHIVE_COPY_INCOMPLETE'):
        service.complete(bundle,'attempt-incomplete')
    member = bundle.members[0]
    reservation = service.reserve(bundle,member,'drive_file_candidate_one')
    metadata = drive_metadata(bundle,member,reservation)
    with pytest.raises(transfer.ArchiveTransferError,match='DRIVE_READBACK_MISMATCH'):
        service.record_verified_bytes(bundle,member,metadata,actual_sha256='0'*64,
            actual_size=member.size_bytes,execution_id='wrong-hash',account_permission_id='owner-permission-1')
    assert not any('/complete/' in key for key in service.client.objects)


def test_complete_copy_is_immutable_idempotent_and_separate_from_cleanup(service,bundle):
    record_all(service,bundle)
    first = service.complete(bundle,'execution-first')
    state = dict(service.client.objects)
    again = service.complete(bundle,'execution-retry')
    assert first == again
    assert service.client.objects == state
    assert first['objects_verified'] == len(bundle.members)
    assert first['history_cleanup_authorised'] is False
    page = service.plan('REFERENCE_HISTORY')
    assert page['archives'][0]['copy_status'] == 'RECORDED_BYTES_VERIFIED'
    assert page['drive_current_availability'] == 'NOT_ASSESSED'


def test_manifest_pagination_does_not_omit_or_duplicate_bundles(service):
    expected = {history_fixture(service,raw=f'{{"test":{index}}}\n'.encode())[0] for index in range(3)}
    seen, cursor = [], None
    for _ in range(10):
        page = service.plan('REFERENCE_HISTORY',cursor=cursor,limit=1)
        seen.extend(row['manifest_sha256'] for row in page['archives'])
        if not page['has_more']:
            break
        assert page['next_cursor'] != cursor
        cursor = page['next_cursor']
    assert len(seen) == len(expected) and set(seen) == expected
    with pytest.raises(transfer.ArchiveTransferError,match='INVALID_PLAN_CURSOR'):
        service.plan('REFERENCE_HISTORY',cursor='../private-media/secret')


def test_empty_history_or_unrelated_exports_cannot_establish_drive_backup(service):
    service.client.objects['drop-rate/exports/'+'a'*64+'.csv'] = b'unrelated export'
    for kind in transfer.KINDS:
        page = service.plan(kind)
        assert page['archives'] == [] and page['scan_scope'] == 'PAGE'
        assert page['drive_current_availability'] == 'NOT_ASSESSED'
        assert page['history_cleanup_authorised'] is False


def test_legacy_history_json_manifest_is_supported(service):
    sha,_,_ = history_fixture(service)
    old = f'drop-rate/reference-history/{sha}.manifest.json'
    service.client.objects[f'drop-rate/reference-history/{sha}.json'] = service.client.objects.pop(old)
    assert service.load_archive('REFERENCE_HISTORY',sha).manifest_sha256 == sha
    assert service.plan('REFERENCE_HISTORY')['archives'][0]['manifest_sha256'] == sha


def test_legacy_and_canonical_manifest_are_not_counted_twice(service):
    sha,_,_ = history_fixture(service)
    service.client.objects[f'drop-rate/reference-history/{sha}.json'] = service.client.objects[
        f'drop-rate/reference-history/{sha}.manifest.json']
    seen, cursor = [], None
    for _ in range(5):
        page = service.plan('REFERENCE_HISTORY',cursor=cursor,limit=1)
        seen.extend(row['manifest_sha256'] for row in page['archives'])
        if not page['has_more']:
            break
        cursor = page['next_cursor']
    assert seen == [sha]


def test_unrelated_export_keys_cannot_starve_manifest_pagination(service,monkeypatch):
    # Arbitrary unrelated export names may appear before valid content-addressed
    # archive manifests. They are cursor positions, never downloadable members.
    monkeypatch.setattr(transfer,'MAX_LIST_KEYS',2)
    for name in ('000-other.txt','001-other/with spaces.zip','002-unrelated'):
        service.client.objects['drop-rate/exports/'+name] = b'not an archive'
    cursor = None
    pages = 0
    while True:
        page = service.plan('OPENLIBRARY_REVIEWED',cursor=cursor)
        pages += 1
        assert page['archives'] == [] and page['blocked_archives'] == []
        if not page['has_more']:
            break
        assert page['next_cursor'] != cursor
        cursor = page['next_cursor']
        with pytest.raises(transfer.ArchiveTransferError,match='INVALID_PLAN_CURSOR'):
            service.plan('REFERENCE_HISTORY',cursor=cursor)
    assert pages == 2


def test_oversized_manifest_reports_size_without_claiming_no_work(service):
    declared = transfer.MAX_OBJECT_BYTES + 500
    sha,_,_ = history_fixture(service,change={'gzip_bytes':declared})
    page = service.plan('REFERENCE_HISTORY')
    assert page['archives'] == []
    assert page['blocked_archives'] == [{'manifest_sha256':sha,'reason':'OBJECT_TOO_LARGE',
        'declared_size_bytes':declared,'maximum_object_bytes':transfer.MAX_OBJECT_BYTES}]
    assert page['drive_current_availability'] == 'NOT_ASSESSED'


@pytest.mark.asyncio
async def test_executor_submission_failure_releases_bounded_slot(monkeypatch):
    loop = asyncio.get_running_loop()
    original = loop.run_in_executor
    def failed(*_args):
        raise RuntimeError('synthetic executor unavailable')
    monkeypatch.setattr(loop,'run_in_executor',failed)
    with pytest.raises(RuntimeError,match='synthetic executor unavailable'):
        await transfer.storage_call(lambda:None)
    monkeypatch.setattr(loop,'run_in_executor',original)
    assert transfer._storage_slots.acquire(blocking=False)
    assert transfer._storage_slots.acquire(blocking=False)
    assert not transfer._storage_slots.acquire(blocking=False)
    transfer._storage_slots.release()
    transfer._storage_slots.release()
    assert await transfer.storage_call(lambda:'recovered') == 'recovered'


@pytest.mark.asyncio
async def test_actual_reviewed_source_archiver_output_is_transport_compatible(service):
    from app.catalogue_source_archives import archive_reviewed_openlibrary_sources
    # Real repository byte pins, real producer, real storage uploader/readback;
    # only the S3 transport is synthetic. No hand-shaped source manifest.
    store = S3ObjectStorage(service.config,client=service.client)
    report = await archive_reviewed_openlibrary_sources(apply=True,storage=store)
    bundle = service.load_archive('OPENLIBRARY_REVIEWED',report['manifest_object']['sha256'])
    assert report['file_count'] == 14 and report['source_bytes'] == 6_228_589
    assert len(bundle.members) == 15
    for member in bundle.members:
        staged = service.stage(bundle,member)
        assert staged.path.stat().st_size == member.size_bytes <= transfer.MAX_OBJECT_BYTES
        staged.cleanup()
    page = service.plan('OPENLIBRARY_REVIEWED')
    assert page['archives'][0]['manifest_sha256'] == bundle.manifest_sha256
