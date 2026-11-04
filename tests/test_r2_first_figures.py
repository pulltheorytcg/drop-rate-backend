"""Local curated figure references only; no external requests or database writes."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app import r2_first_catalogue as codec
from app import r2_first_figures as figures
from app import r2_first_sources as sources


def payload():
    return json.loads(figures._STARTER_PATH.read_bytes())


def descriptor():
    return sources.SourceDescriptor(figures.PROVIDER, figures.SYSTEM_CODE,
        figures.SOURCE_URL, figures.SOURCE_REVISION, figures.PERMISSION_REF,
        "METADATA_ACCESS_DOCUMENTED", figures.SOURCE_URL, figures.MAX_BYTES,
        catalogue_language=figures.CATALOGUE_LANGUAGE)


def test_curated_starter_is_exactly_four_new_funko_references():
    source = payload()
    before = deepcopy(source)
    rows = figures.normalize_figures(source)
    assert source == before
    assert len(rows) == figures.EXPECTED_ROWS == 4
    assert {row["provider_id"] for row in rows} == {
        "funko:43263", "funko:5305", "funko:80341", "funko:90617"}
    assert all(row["provider_id"].startswith("funko:") for row in rows)
    source["figures"].reverse()
    assert figures.normalize_figures(source) == rows
    assert "not a complete" in source["coverage_notice"]
    assert "not duplicated" in source["coverage_notice"]


def test_output_is_factual_unreviewed_reference_not_a_physical_item():
    rows = figures.normalize_figures(payload())
    for row in rows:
        assert set(row) == sources.NORMALIZED_FIELDS | {"details"}
        assert row["provider"] == figures.PROVIDER and row["system_code"] == "FIGURES"
        assert row["product_type"] == "FIGURE" and row["language"] == "Not applicable"
        assert row["source_url"] == figures.SOURCE_URL
        assert row["card_number"] == ""
        assert row["rarity"] is row["finish"] is row["release_date"] is None
        details = row["details"]
        assert details["reference_scope"] == figures.REFERENCE_SCOPE
        assert details["source_record_id"] == row["provider_id"]
        assert details["source_credit"] == "Funko"
        assert details["source_reviewed_at"] == figures.REVIEWED_AT
        assert details["manufacturer"] == "Funko" and details["product_line"] == "Pop!"
        assert "funko:" + details["manufacturer_sku"] == row["provider_id"]
        assert details["source_evidence_url"] == figures._FUNKO_SOURCES[row["provider_id"]][0]
        for excluded in ("edition", "variant", "source_year", "barcode_gtin", "source_license",
                         "language", "owner", "id", "identity_key", "identity_status"):
            assert excluded not in details
        for excluded in ("market_value", "price", "image_url", "description", "owner_id", "id"):
            assert excluded not in row
    by_id = {row["provider_id"]: row for row in rows}
    assert by_id["funko:43263"]["details"]["box_number"] == "553"
    assert by_id["funko:5305"]["details"]["box_number"] == "98"
    assert by_id["funko:80341"]["details"]["box_number"] == "1963"
    assert by_id["funko:90617"]["details"]["box_number"] == "2228"


def test_default_english_argument_never_assigns_english_to_a_figure():
    assert figures.normalize_figures(payload(), "English") == figures.normalize_figures(payload())


@pytest.mark.parametrize("language", ["Japanese", "French", "en", None, [], True])
def test_other_languages_cannot_change_the_partition_scope(language):
    with pytest.raises(sources.SourceError, match="language"):
        figures.normalize_figures(payload(), language)


@pytest.mark.parametrize("change", [
    lambda p: p.update(schema="unreviewed-v2"),
    lambda p: p.update(reference_scope="PHYSICAL_IDENTITY_APPROVED"),
    lambda p: p.update(reviewed_at="2027-11-04"),
    lambda p: p.update(reviewed_at="2026-02-30"),
    lambda p: p.update(figures=[]),
    lambda p: p["figures"].append(deepcopy(p["figures"][0])),
    lambda p: p["figures"].__setitem__(0, None),
    lambda p: p["figures"][0].update(source_id="funko:11111"),
    lambda p: p["figures"][0].update(source_id="goodsmile:1136133"),
    lambda p: p["figures"][0].update(product_type="CARD"),
    lambda p: p["figures"][0].update(product_type="PLUSH"),
    lambda p: p["figures"][0].update(manufacturer="Other"),
    lambda p: p["figures"][0].update(product_line="Pop! Tee"),
    lambda p: p["figures"][0].update(source_url="http://127.0.0.1/private"),
    lambda p: p["figures"][0].update(source_url=figures.SOURCE_URL),
    lambda p: p["figures"][0].update(source_checked_at="2026-11-05"),
    lambda p: p["figures"][0].update(source_checked_at=None),
    lambda p: p["figures"][0].update(manufacturer_sku="553"),
    lambda p: p["figures"][0].update(box_number=""),
    lambda p: p["figures"][0].update(box_number=553),
    lambda p: p["figures"][0].update(box_number="001"),
    lambda p: p["figures"][0].update(box_number="999999999"),
    lambda p: p["figures"][0].update(name=""),
    lambda p: p["figures"][0].update(name="x" * 513),
    lambda p: p["figures"][0].update(character="Hidden\u200bcontrol"),
    lambda p: p["figures"][0].update(franchise="Name\nInjected"),
    lambda p: p["figures"][0].update(name=" Not canonical whitespace "),
    lambda p: p["figures"][0].update(edition="Standard"),
    lambda p: p["figures"][0].update(variant="No chase"),
    lambda p: p["figures"][0].update(source_year="2026"),
    lambda p: p["figures"][0].update(language="English"),
    lambda p: p["figures"][0].update(image_url="https://private.invalid/image"),
    lambda p: p["figures"][0].update(price=1),
    lambda p: p["figures"][0].update(description="Unreviewed copyrighted prose"),
    lambda p: p["figures"][0].update(id="canonical-existing-id"),
])
def test_invalid_unreviewed_or_excess_fields_fail_closed(change):
    source = payload()
    change(source)
    with pytest.raises(sources.SourceError):
        figures.normalize_figures(source)


def test_duplicate_source_reference_is_rejected_without_collapsing_it():
    source = payload()
    source["figures"][1] = deepcopy(source["figures"][0])
    with pytest.raises(sources.SourceError, match="Duplicate"):
        figures.normalize_figures(source)


@pytest.mark.asyncio
async def test_local_fetch_reads_only_new_starter_and_never_uses_http(monkeypatch):
    content = figures._STARTER_PATH.read_bytes()
    existing_path = figures._DATA_DIR / "collectible_catalogue_starter_20261103.json"
    existing_before = existing_path.read_bytes()
    requests, local_reads = AsyncMock(), []
    original_open = Path.open
    def read_only_starter(path, mode="r", *args, **kwargs):
        assert path == figures._STARTER_PATH and mode == "rb"
        local_reads.append(path)
        return io.BytesIO(content)
    monkeypatch.setattr(Path, "open", read_only_starter)
    async with httpx.AsyncClient(transport=httpx.MockTransport(requests)) as client:
        result = await figures.fetch_figures(client, descriptor())
    requests.assert_not_called()
    assert local_reads == [figures._STARTER_PATH]
    assert result.record_count == 4 and result.records == figures.normalize_figures(json.loads(content))
    assert result.source_sha256 == hashlib.sha256(content).hexdigest()
    assert result.source_revision == "sha256:" + result.source_sha256
    assert result.source_url == figures.SOURCE_URL
    monkeypatch.setattr(Path, "open", original_open)
    assert existing_path.read_bytes() == existing_before
    existing = json.loads(existing_before)
    assert {row["source_id"] for row in existing["entries"] if row["figure_details"]} == {
        "goodsmile:1136133", "goodsmile:1139898"}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"provider": "funko"}, {"system_code": "POKEMON"}, {"source_revision": "unreviewed"},
    {"source_url": "file:///etc/passwd"}, {"download_url": "https://funko.com/api/"},
    {"download_url": None}, {"permission_ref": "https://funko.com/"},
    {"permission_status": "REVIEW_REQUIRED"}, {"max_bytes": figures.MAX_BYTES + 1},
    {"catalogue_language": "English"},
])
async def test_descriptor_cannot_select_a_path_url_scope_or_larger_limit(change, monkeypatch):
    load = AsyncMock()
    monkeypatch.setattr(figures.asyncio, "to_thread", load)
    requests = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(requests)) as client:
        with pytest.raises(sources.SourcePermissionError):
            await figures.fetch_figures(client, replace(descriptor(), **change))
    requests.assert_not_called()
    load.assert_not_called()


@pytest.mark.parametrize("content", [b"", b"x" * (figures.MAX_BYTES + 1)])
def test_local_read_is_bounded_and_empty_or_oversized_files_fail(content, monkeypatch):
    reads = []
    class BoundedBuffer(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: BoundedBuffer(content))
    with pytest.raises(sources.SourceError, match="Empty or oversized"):
        figures._read_local(figures._STARTER_PATH)
    assert reads == [figures.MAX_BYTES + 1]


def test_missing_local_file_fails_without_falling_back_to_network(monkeypatch):
    def fail(*args, **kwargs):
        raise FileNotFoundError("private path")
    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(sources.SourceError, match="unavailable") as error:
        figures._load_local()
    assert "private path" not in str(error.value)


@pytest.mark.parametrize("content", [b'{"figures":[],"figures":[]}', b'{"figures":NaN}', b'\xff', b'{'])
def test_invalid_local_json_fails_closed(content, monkeypatch):
    monkeypatch.setattr(figures, "_read_local", lambda _: content)
    with pytest.raises(sources.SourceError, match="source JSON"):
        figures._load_local()


@pytest.mark.asyncio
async def test_public_dispatch_requires_approval_and_is_local_only():
    assert sources.source_descriptor(figures.PROVIDER) == descriptor()
    assert sources.source_descriptor(figures.PROVIDER, "Not applicable") == descriptor()
    requests = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(requests)) as client:
        with pytest.raises(sources.SourcePermissionError):
            await sources.fetch_source(figures.PROVIDER, client)
        result = await sources.fetch_source(figures.PROVIDER, client,
            approved_sources={figures.PROVIDER})
    assert result.record_count == 4
    requests.assert_not_called()


@pytest.mark.asyncio
async def test_r2_codec_roundtrip_preserves_box_facts_and_reference_only_status():
    class MemoryStore:
        def __init__(self):
            self.objects = {}

        def put_verified_reference_snapshot(self, raw):
            digest = hashlib.sha256(raw).hexdigest()
            self.objects[digest] = raw
            return {"sha256": digest, "verified": True}

        def read_verified_reference_snapshot(self, digest):
            return self.objects[digest]

    rows = figures.normalize_figures(payload())
    bundle = codec.prepare_catalogue(rows, provider=figures.PROVIDER,
        system_code=figures.SYSTEM_CODE, language=figures.CATALOGUE_LANGUAGE,
        source_url=figures.SOURCE_URL, source_revision=figures.SOURCE_REVISION,
        permission_ref=figures.PERMISSION_REF)
    storage = MemoryStore()
    manifest = await codec.upload_and_verify(bundle, storage)
    snapshot = await codec.load_catalogue(manifest, storage)
    try:
        assert snapshot.search(product_type="FIGURE")["total"] == 4
        assert snapshot.search(product_type="CARD")["total"] == 0
        assert snapshot.search(q="Hatsune")["total"] == 0
        pikachu, = snapshot.search(q="Pikachu")["items"]
        assert pikachu["language"] == "Not applicable" and pikachu["card_number"] == ""
        assert pikachu["details"]["box_number"] == "553"
        assert pikachu["details"]["manufacturer_sku"] == "43263"
        assert pikachu["details"]["reference_scope"] == figures.REFERENCE_SCOPE
        assert "edition" not in pikachu["details"] and "source_year" not in pikachu["details"]
        assert snapshot.get(pikachu["key"]) == pikachu
    finally:
        snapshot.close()
