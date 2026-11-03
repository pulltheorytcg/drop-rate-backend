"""R2-first source files/indexes never depend on source-table PostgreSQL rows."""

import asyncio
import copy
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import threading

import pytest

from app import r2_first_catalogue as catalogue


def row(provider_id="one", **changes):
    value = {"provider": "ReviewedProvider", "system_code": "LORCANA",
             "language": "English", "provider_id": provider_id,
             "product_type": "CARD", "name": "Mickey — Brave Little Tailor",
             "set_id": "first-chapter", "set_name": "The First Chapter",
             "card_number": "115/204", "rarity": "Legendary", "finish": None,
             "release_date": "2023-08-18", "source_url": "https://provider.example.com/cards/one"}
    value.update(changes)
    return value


def prepare(rows=None, **changes):
    scope = {"provider": "ReviewedProvider", "system_code": "LORCANA", "language": "English",
             "source_url": "https://provider.example.com/data", "source_revision": "2026-11-03",
             "permission_ref": "docs/provider-review-20261103.md"}
    scope.update(changes)
    return catalogue.prepare_catalogue(rows if rows is not None else [row()], **scope)


class Storage:
    def __init__(self):
        self.objects = {}
        self.puts = []
        self.reads = []
        self.fail_write = None
        self.fail_read = None
        self.bad_receipt = False

    def put_verified_reference_snapshot(self, raw):
        digest = hashlib.sha256(raw).hexdigest()
        if self.fail_write == digest:
            raise OSError("upload failed")
        if digest not in self.objects:
            self.puts.append(digest)
            self.objects[digest] = raw
        return {"sha256": "a" * 64 if self.bad_receipt else digest, "verified": True,
                "key": "private/content/" + digest, "size_bytes": len(raw),
                "compressed_sha256": "b" * 64}

    def read_verified_reference_snapshot(self, digest):
        self.reads.append(digest)
        if self.fail_read == digest:
            raise OSError("readback failed")
        return self.objects[digest]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def retarget_part(manifest, payload):
    """Give malicious bytes honest byte hashes to test the semantic boundary."""
    forged = copy.deepcopy(manifest)
    digest = hashlib.sha256(payload).hexdigest()
    forged["parts"][0]["sha256"] = digest
    forged["parts"][0]["raw_bytes"] = len(payload)
    forged["raw_bytes"] = sum(part["raw_bytes"] for part in forged["parts"])
    return forged, digest


def test_key_is_exact_json_identity_tuple_not_title_or_printing_guess():
    key = catalogue.stable_key("Provider", "LORCANA", "English", "a/b")
    assert key == "x:" + hashlib.sha256(encoded(["Provider", "LORCANA", "English", "a/b"])).hexdigest()
    assert key != catalogue.stable_key("Provider", "LORCANA", "Japanese", "a/b")
    assert key != catalogue.stable_key("Provider", "LORCANA", "English", "a-b")
    assert key != catalogue.stable_key("Other", "LORCANA", "English", "a/b")
    with pytest.raises(catalogue.R2FirstCatalogueError):
        catalogue.stable_key("Provider/LORCANA", "LORCANA", "English", "a/b")


def test_input_order_retries_and_defensive_manifest_are_deterministic():
    rows = [row("two"), row("one"), row("three")]
    first = prepare(rows)
    second = prepare(reversed(rows))
    assert first == second
    assert first.manifest_digest == catalogue.manifest_digest(first.manifest)
    assert first._manifest_bytes == catalogue.canonical_manifest_bytes(first.manifest)
    mutable = first.manifest
    mutable["parts"][0]["sha256"] = "f" * 64
    assert first.manifest["parts"][0]["sha256"] != "f" * 64
    assert prepare(rows, permission_ref="review:other").manifest_digest != first.manifest_digest
    assert prepare(rows, source_revision="next").manifest_digest != first.manifest_digest


@pytest.mark.parametrize("change", [{}, {"name": "Conflicting printing"}, {"finish": "Foil"}])
def test_duplicates_always_fail_even_if_rows_are_identical(change):
    with pytest.raises(catalogue.R2FirstCatalogueError, match="Duplicate exact"):
        prepare([row(), row(**change)])


@pytest.mark.parametrize("field", ["price", "owner_id", "cost", "stock", "image_url", "attributes", "key"])
def test_unreviewed_price_media_private_or_identity_fields_are_rejected(field):
    with pytest.raises(catalogue.R2FirstCatalogueError, match="fields"):
        prepare([row(**{field: "must not be archived"})])


@pytest.mark.parametrize("change", [
    {"provider": "Other"}, {"system_code": "YU_GI_OH"}, {"language": "Japanese"},
    {"provider_id": ""}, {"provider_id": "a" * 257}, {"name": ""},
    {"name": "a\x00b"}, {"name": "a\nb"}, {"name": "a\u202eb"},
    {"name": " white space "}, {"name": "a" * 513}, {"product_type": "INVENTORY"},
    {"release_date": "2026-02-30"}, {"release_date": "2026-2-3"},
    {"release_date": 20261103}, {"rarity": {"value": "Common"}}, {"finish": ""},
    {"details": {"image_url": "https://provider.example.com/image"}},
    {"details": {"edition": None}}, {"details": {"edition": "a" * 257}},
])
def test_source_rows_are_closed_bounded_and_partition_exact(change):
    with pytest.raises(catalogue.R2FirstCatalogueError):
        prepare([row(**change)])


@pytest.mark.parametrize("url", [
    "http://provider.example.com/data", "https://user:password@provider.example.com/data",
    "https://provider.example.com/data?token=secret", "https://provider.example.com/data#fragment",
    "https://provider.example.com/data?", "https://provider.example.com/data#",
    "https://127.0.0.1/data", "https://10.0.0.1/data", "https://[::1]/data",
    "https://localhost/data", "https://host.local/data", "https://host.internal/data",
    "https://host.lan/data", "https://host.invalid/data", "https://host.test/data",
    "https://provider.example.com./data", "https://provider.example.com:443/data",
    "https://provider.example.com/a\\b", "https://provider.example.com/a%00b",
    "https://provider.example.com/a%0ab", "https://provider.example.com/a b",
    "https://provider.example.com\n/data", "file:///private",
])
def test_urls_cannot_contain_credentials_local_hosts_or_unsafe_components(url):
    with pytest.raises(catalogue.R2FirstCatalogueError):
        prepare(source_url=url)
    with pytest.raises(catalogue.R2FirstCatalogueError):
        prepare([row(source_url=url)])


def test_nullable_metadata_unknown_set_and_figure_details_are_not_invented():
    bundle = prepare([row(product_type="FIGURE", set_id="", set_name="", card_number="",
                          rarity=None, finish=None, release_date=None,
                          details={"variant": "Chase", "franchise": "Disney"})])
    stored = json.loads(bundle.parts[0])[0]
    assert stored["product_type"] == "FIGURE" and stored["rarity"] is None
    assert stored["details"] == {"variant": "Chase", "franchise": "Disney"}


def test_count_byte_and_empty_input_bounds(monkeypatch):
    with pytest.raises(catalogue.R2FirstCatalogueError, match="Empty"):
        prepare([])
    monkeypatch.setattr(catalogue, "MAX_ROWS", 2)
    with pytest.raises(catalogue.R2FirstCatalogueError, match="row bound"):
        prepare([row("1"), row("2"), row("3")])
    monkeypatch.setattr(catalogue, "MAX_RAW_BYTES", 20)
    with pytest.raises(catalogue.R2FirstCatalogueError, match="byte bound"):
        prepare()


def test_shards_are_sorted_and_row_bounded():
    bundle = prepare(row(str(number)) for number in range(503))
    assert [part["rows"] for part in bundle.manifest["parts"]] == [500, 3]
    keys = [value["key"] for payload in bundle.parts for value in json.loads(payload)]
    assert keys == sorted(keys)
    assert len(set(keys)) == 503
    assert all(len(part) <= catalogue.MAX_PART_BYTES for part in bundle.parts)


def test_shards_respect_raw_bytes_even_before_row_cap(monkeypatch):
    monkeypatch.setattr(catalogue, "MAX_PART_BYTES", 1100)
    bundle = prepare([row("one"), row("two"), row("three")])
    assert len(bundle.parts) >= 2
    assert all(len(part) <= 1100 for part in bundle.parts)


@pytest.mark.parametrize("change", [
    lambda m: m.update(schema="another-schema"),
    lambda m: m.update(private_owner="excluded"),
    lambda m: m.update(record_count=True),
    lambda m: m.update(record_count=2),
    lambda m: m.update(raw_bytes=m["raw_bytes"] + 1),
    lambda m: m.update(content_sha256="../path"),
    lambda m: m["parts"][0].update(ordinal=True),
    lambda m: m["parts"][0].update(ordinal=1),
    lambda m: m["parts"][0].update(rows=501),
    lambda m: m["parts"][0].update(owner_id="excluded"),
    lambda m: m["parts"].append(copy.deepcopy(m["parts"][0])),
    lambda m: m["parts"][0].update(first_key="x:" + "f" * 64),
])
def test_manifest_schema_hash_ranges_counts_and_order_are_validated(change):
    manifest = prepare().manifest
    change(manifest)
    with pytest.raises(catalogue.R2FirstCatalogueError):
        catalogue.validate_manifest(manifest)


@pytest.mark.asyncio
async def test_verified_upload_is_idempotent_and_manifest_is_uploaded_last():
    store = Storage()
    bundle = prepare(row(str(number)) for number in range(501))
    manifest = await catalogue.upload_and_verify(bundle, store)
    assert store.puts == [part["sha256"] for part in manifest["parts"]] + [bundle.manifest_digest]
    assert store.reads == store.puts
    assert await catalogue.upload_and_verify(bundle, store) == manifest
    assert len(store.puts) == 3
    assert await catalogue.load_manifest(bundle.manifest_digest, store) == manifest


@pytest.mark.asyncio
async def test_partial_upload_does_not_publish_manifest_and_retry_is_safe():
    store = Storage()
    bundle = prepare(row(str(number)) for number in range(501))
    store.fail_write = bundle.manifest["parts"][1]["sha256"]
    with pytest.raises(catalogue.R2FirstCatalogueError, match="upload"):
        await catalogue.upload_and_verify(bundle, store)
    assert bundle.manifest_digest not in store.objects
    assert len(store.puts) == 1
    store.fail_write = None
    assert await catalogue.upload_and_verify(bundle, store) == bundle.manifest
    assert len(store.puts) == 3


@pytest.mark.asyncio
async def test_upload_never_accepts_wrong_receipt_or_unreadable_object():
    bundle = prepare()
    store = Storage()
    store.bad_receipt = True
    with pytest.raises(catalogue.R2FirstCatalogueError, match="receipt"):
        await catalogue.upload_and_verify(bundle, store)
    assert bundle.manifest_digest not in store.objects
    store.bad_receipt = False
    store.fail_read = bundle.manifest["parts"][0]["sha256"]
    with pytest.raises(catalogue.R2FirstCatalogueError, match="readback"):
        await catalogue.upload_and_verify(bundle, store)
    assert bundle.manifest_digest not in store.objects


@pytest.mark.asyncio
async def test_forged_prepared_bundle_is_validated_before_any_upload():
    bundle = prepare()
    store = Storage()
    forged = catalogue.PreparedCatalogue(bundle._manifest_bytes, (bundle.parts[0] + b" ",))
    with pytest.raises(catalogue.R2FirstCatalogueError):
        await catalogue.upload_and_verify(forged, store)
    assert store.puts == [] and store.reads == []


@pytest.mark.asyncio
async def test_loaded_runtime_search_get_sets_pagination_and_future_gate():
    bundle = prepare([
        row("first", name="Alpha Character", card_number="001/200", release_date="2023-08-18"),
        row("second", name="Beta Character", card_number="002/200", release_date="2024-01-01"),
        row("third", name="Gamma Character", set_id="other", set_name="Another Set", release_date=None),
        row("upcoming", name="Future Character", release_date="2099-01-01"),
    ])
    store = Storage()
    manifest = await catalogue.upload_and_verify(bundle, store)
    snapshot = await catalogue.load_catalogue(manifest, store)
    try:
        assert snapshot.record_count == 4
        assert (snapshot.provider, snapshot.system_code, snapshot.language) == (
            "ReviewedProvider", "LORCANA", "English")
        assert snapshot.manifest == manifest and snapshot.manifest_digest == bundle.manifest_digest
        assert snapshot.search(today=date(2026, 11, 3))["total"] == 3
        assert snapshot.search(include_upcoming=True)["total"] == 4
        assert [r["name"] for r in snapshot.search(limit=1, offset=1)["items"]] == ["Beta Character"]
        assert snapshot.search(q="aLpHa")["items"][0]["provider_id"] == "first"
        assert snapshot.search(q="002/200")["items"][0]["provider_id"] == "second"
        assert snapshot.search(q="Other", set_id="other")["total"] == 1
        assert snapshot.search(q="%_' OR 1=1 --")["total"] == 0
        assert snapshot.search(q="a")["total"] == 3  # shorter than trigram index minimum
        assert snapshot.search(sort="newest")["items"][0]["provider_id"] == "second"
        assert snapshot.search(sort="oldest")["items"][0]["provider_id"] == "first"
        assert snapshot.search(sort="number")["items"][0]["provider_id"] == "first"
        assert snapshot.search(sort="name_desc")["items"][0]["provider_id"] == "third"
        key = catalogue.stable_key("ReviewedProvider", "LORCANA", "English", "first")
        found = snapshot.get(key)
        assert found["name"] == "Alpha Character"
        found["name"] = "not persisted"
        assert snapshot.get(key)["name"] == "Alpha Character"
        assert snapshot.get("x:" + "0" * 64) is None
        assert snapshot.sets() == [
            {"set_id": "other", "set_name": "Another Set", "count": 1},
            {"set_id": "first-chapter", "set_name": "The First Chapter", "count": 2}]
        assert sum(item["count"] for item in snapshot.sets(include_upcoming=True)) == 4
        assert snapshot._connection.execute("pragma cache_size").fetchone()[0] == -8192
        assert snapshot._connection.execute("pragma query_only").fetchone()[0] == 1
    finally:
        path = Path(snapshot._directory.name)
        snapshot.close()
        snapshot.close()
        assert not path.exists()
    with pytest.raises(catalogue.R2FirstCatalogueError, match="unavailable"):
        snapshot.search()


@pytest.mark.asyncio
async def test_unicode_and_punctuation_substrings_are_not_identity_normalization():
    rows = [row("jp-one", name="ミッキーマウス", card_number="ABC-101", details={"edition": 'First "A"'}),
            row("jp-two", name="ミッキーマウス", card_number="ABC-102")]
    bundle = prepare(rows)
    store = Storage()
    await catalogue.upload_and_verify(bundle, store)
    with await catalogue.load_catalogue(bundle.manifest, store) as snapshot:
        assert snapshot.search(q="ミッキー")["total"] == 2
        assert snapshot.search(q="ABC-10")["total"] == 2
        assert snapshot.search(q='First "A"')["total"] == 1
        assert snapshot.search(q="ミッキーマウス")["items"][0]["key"] != snapshot.search(
            q="ミッキーマウス")["items"][1]["key"]


@pytest.mark.parametrize("kwargs", [
    {"limit": 0}, {"limit": 101}, {"limit": True}, {"offset": -1}, {"offset": True},
    {"sort": "price"}, {"q": "a\x00b"}, {"q": "a" * 201},
    {"set_id": "a" * 257}, {"include_upcoming": "yes"}, {"today": "2026-11-03"},
])
@pytest.mark.asyncio
async def test_runtime_rejects_unbounded_or_unsupported_query_shapes(kwargs):
    store = Storage()
    bundle = prepare()
    await catalogue.upload_and_verify(bundle, store)
    with await catalogue.load_catalogue(bundle.manifest, store) as snapshot:
        with pytest.raises(catalogue.R2FirstCatalogueError):
            snapshot.search(**kwargs)


@pytest.mark.asyncio
async def test_manifest_missing_corrupt_wrong_digest_or_duplicate_json_keys_fails():
    store = Storage()
    bundle = prepare()
    with pytest.raises(catalogue.R2FirstCatalogueError):
        await catalogue.load_manifest("a" * 64, store)
    with pytest.raises(catalogue.R2FirstCatalogueError):
        await catalogue.load_manifest("../private", store)
    await catalogue.upload_and_verify(bundle, store)
    store.objects[bundle.manifest_digest] += b" "
    with pytest.raises(catalogue.R2FirstCatalogueError, match="integrity"):
        await catalogue.load_manifest(bundle.manifest_digest, store)
    duplicate = bundle._manifest_bytes.replace(b'"schema":', b'"schema":"duplicate","schema":', 1)
    digest = hashlib.sha256(duplicate).hexdigest()
    store.objects[digest] = duplicate
    with pytest.raises(catalogue.R2FirstCatalogueError):
        await catalogue.load_manifest(digest, store)


@pytest.mark.parametrize("change", [
    lambda rows: rows[0].update(owner_id="private"),
    lambda rows: rows[0].update(provider="AnotherProvider"),
    lambda rows: rows[0].update(key="x:" + "a" * 64),
    lambda rows: rows[0].update(details={"price": "20"}),
])
@pytest.mark.asyncio
async def test_honestly_hashed_objects_still_reject_semantic_private_or_scope_drift(change):
    bundle = prepare()
    rows = json.loads(bundle.parts[0])
    change(rows)
    payload = encoded(rows)
    manifest, digest = retarget_part(bundle.manifest, payload)
    store = Storage()
    store.objects[digest] = payload
    with pytest.raises(catalogue.R2FirstCatalogueError):
        await catalogue.load_catalogue(manifest, store)


@pytest.mark.asyncio
async def test_missing_part_or_content_digest_never_returns_partial_snapshot(monkeypatch):
    bundle = prepare(row(str(number)) for number in range(501))
    store = Storage()
    await catalogue.upload_and_verify(bundle, store)
    directories = []
    original = catalogue._temporary_connection

    def capture_directory():
        directory, connection = original()
        directories.append(Path(directory.name))
        return directory, connection

    monkeypatch.setattr(catalogue, "_temporary_connection", capture_directory)
    store.fail_read = bundle.manifest["parts"][1]["sha256"]
    with pytest.raises(catalogue.R2FirstCatalogueError, match="unavailable"):
        await catalogue.load_catalogue(bundle.manifest, store)
    assert directories and all(not path.exists() for path in directories)
    store.fail_read = None
    manifest = bundle.manifest
    manifest["content_sha256"] = "f" * 64
    with pytest.raises(catalogue.R2FirstCatalogueError, match="content digest"):
        await catalogue.load_catalogue(manifest, store)
    assert all(not path.exists() for path in directories)


@pytest.mark.asyncio
async def test_wrong_part_hash_order_or_count_fails_without_sql_fallback():
    bundle = prepare([row("one"), row("two")])
    store = Storage()
    await catalogue.upload_and_verify(bundle, store)
    original = store.objects[bundle.manifest["parts"][0]["sha256"]]
    store.objects[bundle.manifest["parts"][0]["sha256"]] = original + b" "
    with pytest.raises(catalogue.R2FirstCatalogueError, match="integrity"):
        await catalogue.load_catalogue(bundle.manifest, store)
    rows = json.loads(original)
    for mutated in [list(reversed(rows)), [rows[0]], [rows[0], rows[0]]]:
        payload = encoded(mutated)
        manifest, digest = retarget_part(bundle.manifest, payload)
        store.objects[digest] = payload
        with pytest.raises(catalogue.R2FirstCatalogueError):
            await catalogue.load_catalogue(manifest, store)


@pytest.mark.asyncio
async def test_existing_immutable_storage_implementation_is_compatible_without_changes():
    from app.object_storage import ObjectStorageConfig, S3ObjectStorage

    class Missing(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    class Client:
        def __init__(self):
            self.objects = {}

        def get_object(self, **kwargs):
            if kwargs["Key"] not in self.objects:
                raise Missing()
            return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

        def put_object(self, **kwargs):
            self.objects[kwargs["Key"]] = kwargs["Body"].read()

    client = Client()
    config = ObjectStorageConfig("https://example.r2.cloudflarestorage.com", "private", "auto", "key", "secret")
    store = S3ObjectStorage(config, client=client)
    bundle = prepare([row("one"), row("two")])
    await catalogue.upload_and_verify(bundle, store)
    manifest = await catalogue.load_manifest(bundle.manifest_digest, store)
    with await catalogue.load_catalogue(manifest, store) as snapshot:
        assert snapshot.search()["total"] == 2
    assert len(client.objects) == 2
    assert all(key.startswith("drop-rate/catalogue-reference-inputs/") for key in client.objects)


@pytest.mark.asyncio
async def test_cancelled_download_closes_unpublished_runtime_index(monkeypatch):
    bundle = prepare()
    store = Storage()
    await catalogue.upload_and_verify(bundle, store)
    started, release = threading.Event(), threading.Event()
    original_read = store.read_verified_reference_snapshot
    original_connection = catalogue._temporary_connection
    directories = []

    def read(digest):
        started.set()
        release.wait(2)
        return original_read(digest)

    def connection():
        directory, conn = original_connection()
        directories.append(Path(directory.name))
        return directory, conn

    monkeypatch.setattr(store, "read_verified_reference_snapshot", read)
    monkeypatch.setattr(catalogue, "_temporary_connection", connection)
    task = asyncio.create_task(catalogue.load_catalogue(bundle.manifest, store))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert directories and all(not path.exists() for path in directories)
    finally:
        release.set()


@pytest.mark.asyncio
async def test_rebuildable_snapshot_supports_threaded_readers_and_identical_no_fts_fallback():
    store = Storage()
    bundle = prepare([row("one"), row("two", name="Beta — First Edition")])
    await catalogue.upload_and_verify(bundle, store)
    with await catalogue.load_catalogue(bundle.manifest, store) as snapshot:
        queries = ["Mickey", "115/204", "— B", "---", '"A"', "Beta", "First", "xy"]
        indexed = [snapshot.search(q=query) for query in queries]
        threaded = await asyncio.gather(*(asyncio.to_thread(snapshot.search, query) for query in queries))
        assert indexed == threaded
        snapshot._fts = False
        assert indexed == [snapshot.search(q=query) for query in queries]


@pytest.mark.asyncio
async def test_owner_key_and_product_filters_apply_before_total_and_pagination():
    store = Storage()
    rows = [row("alpha", name="Alpha"), row("beta", name="Beta"), row("gamma", name="Gamma"),
            row("figure", name="A Figure", product_type="FIGURE")]
    bundle = prepare(rows)
    await catalogue.upload_and_verify(bundle, store)
    keys = [catalogue.stable_key("ReviewedProvider", "LORCANA", "English", item["provider_id"])
            for item in rows]
    with await catalogue.load_catalogue(bundle.manifest, store) as snapshot:
        assert snapshot.search(keys=[])["total"] == 0
        assert snapshot.search(keys=None, exclude_keys=[])["total"] == 4
        selected = snapshot.search(keys=keys[:3], exclude_keys=[keys[1]], limit=1, offset=1)
        assert selected["total"] == 2
        assert selected["items"][0]["provider_id"] == "gamma"
        assert snapshot.search(keys=[keys[0], keys[0]])["total"] == 1
        assert snapshot.search(keys=keys[:2], exclude_keys=keys[:2])["total"] == 0
        assert snapshot.search(product_type="CARD")["total"] == 3
        assert snapshot.search(product_type="FIGURE")["items"][0]["provider_id"] == "figure"
        assert snapshot.search(product_type="FIGURE", keys=keys[:3])["total"] == 0
        assert snapshot.search(q="Gamma", keys=keys[:3], exclude_keys=[keys[2]])["total"] == 0
        # Ten thousand keys are one bound parameter, not ten thousand SQL
        # placeholders; caller-owned identities are never persisted.
        large_keys = ["x:" + f"{number:064x}" for number in range(9999)] + [keys[1]]
        assert snapshot.search(keys=large_keys)["total"] == 1
        assert snapshot.search(exclude_keys=large_keys)["total"] == 3
        assert snapshot.record_count == 4


@pytest.mark.parametrize("kwargs", [
    {"keys": "x:" + "a" * 64}, {"keys": ["c:legacy"]},
    {"keys": ["x:" + "A" * 64]}, {"keys": [None]},
    {"keys": ["x:" + "a" * 64] * 10001},
    {"exclude_keys": ["x:" + "a" * 64] * 10001},
    {"exclude_keys": ["x:' OR 1=1 --"]}, {"product_type": "INVENTORY"},
])
@pytest.mark.asyncio
async def test_owner_filter_bounds_and_exact_identity_keys_are_enforced(kwargs):
    store = Storage()
    bundle = prepare()
    await catalogue.upload_and_verify(bundle, store)
    with await catalogue.load_catalogue(bundle.manifest, store) as snapshot:
        with pytest.raises(catalogue.R2FirstCatalogueError):
            snapshot.search(**kwargs)


def test_module_has_no_postgres_network_credentials_or_transactional_domain_dependency():
    import ast
    source = Path(catalogue.__file__).read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"asyncpg", "psycopg", "requests", "httpx", "boto3", "db", "settings"}
    assert "tcg.reference_cards" not in source
    assert "os.environ" not in source
    assert "configured_object_storage" not in source
