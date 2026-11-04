"""Synthetic Heritage references and bounded fake transports; no production I/O."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from app import r2_first_catalogue as codec
from app import r2_first_import as worker
from app import r2_first_service as service
from app import r2_first_sources as sources
from app import r2_first_sports as bowman
from app import r2_first_topps_heritage as heritage


ACTOR = UUID("11111111-1111-4111-8111-111111111111")


def payload(count=1):
    return {"title": heritage.SOURCE_TITLE, "reviewedDate": heritage.SOURCE_REVIEWED_DATE,
        "sourceUrl": heritage.SOURCE_EVIDENCE_URL, "sourceSha256": heritage.SOURCE_EVIDENCE_SHA256,
        "count": heritage.EXPECTED_ROWS,
        "cards": [{"number": index, "subjects": [f"Fixture Player {index}"],
                   "category": "Base Cards", "sourcePages": [1], "note": "",
                   "image_url": "https://private.invalid/no-fetch", "price": 900,
                   "owner_id": "private-owner", "description": "Excluded marketing prose"}
                  for index in range(1, count + 1)]}


def descriptor():
    return sources.SourceDescriptor(heritage.PROVIDER, heritage.SYSTEM_CODE,
        heritage.DOWNLOAD_URL, heritage.SOURCE_REVISION, heritage.PERMISSION_REF,
        "METADATA_ACCESS_DOCUMENTED", heritage.DOWNLOAD_URL, heritage.MAX_BYTES)


def fixture_bytes(monkeypatch, source=None, *, content=None):
    # Only synthetic HTTP fixtures replace the reviewed digest, not production
    # configuration. The real digest is asserted separately below.
    content = content if content is not None else json.dumps(
        payload(heritage.EXPECTED_ROWS) if source is None else source).encode()
    monkeypatch.setattr(heritage, "REVIEWED_EXPORT_SHA256", hashlib.sha256(content).hexdigest())
    return content


def test_only_factual_reference_fields_and_attribution_leave_adapter():
    source = payload()
    original = deepcopy(source)
    record, = heritage.normalize_topps_heritage(source)
    assert source == original and heritage.normalize_topps_heritage(source) == [record]
    assert set(record) == sources.NORMALIZED_FIELDS | {"details"}
    assert record["provider"] == "cardcollectorcapital_heritage"
    assert record["provider_id"] == "2026-topps-heritage-1"
    assert record["system_code"] == "SPORTS_CARDS" and record["product_type"] == "CARD"
    assert record["name"] == "Fixture Player 1" and record["card_number"] == "1"
    assert record["set_id"] == heritage.SET_ID and record["set_name"] == "2026 Topps Heritage"
    assert record["rarity"] is record["finish"] is record["release_date"] is None
    details = record["details"]
    assert details["source_evidence_url"] == source["sourceUrl"]
    assert details["source_reviewed_at"] == source["reviewedDate"]
    assert details["source_credit"] == heritage.SOURCE_CREDIT
    assert details["source_license"] == heritage.SOURCE_LICENSE
    assert details["reference_scope"] == heritage.REFERENCE_SCOPE
    assert details["manufacturer"] == "Topps" and details["brand"] == "Topps Heritage"
    assert details["checklist_section"] == "Base Cards" and details["source_page"] == "1"
    assert not {"variant", "edition", "team", "language", "grade"} & details.keys()
    serialized = json.dumps(record)
    for excluded in ("private.invalid", "private-owner", "Excluded marketing", '"price"', '"image_url"'):
        assert excluded not in serialized


def test_multi_player_card_is_one_identity_and_preserves_all_evidence_pages():
    source = payload()
    source["cards"][0].update(number=376, category="Quad Rookies",
        subjects=["Fixture One", "Fixture Two", "Fixture Three", "Fixture Four"], sourcePages=[2, 1])
    record, = heritage.normalize_topps_heritage(source)
    assert record["provider_id"] == "2026-topps-heritage-376"
    assert record["name"] == "Fixture One / Fixture Two / Fixture Three / Fixture Four"
    assert record["details"]["player"] == record["name"]
    assert record["details"]["source_page"] == "1, 2"


def test_back_variation_warning_is_evidence_not_an_approved_parallel():
    source = payload()
    source["cards"][0].update(number=360, subjects=["Owen Caissie"], sourcePages=[7],
        note=heritage._BACK_VARIATION_NOTE)
    record, = heritage.normalize_topps_heritage(source)
    assert record["card_number"] == "360"
    assert record["details"]["source_note"] == heritage._BACK_VARIATION_NOTE
    assert "variant" not in record["details"] and record["finish"] is None
    view = service._view({"key": "x:" + "a" * 64, **record}, "b" * 64)
    assert view["sports_card"]["parallel"] is None
    assert "language" not in view["sports_card"]
    assert view["identity_review_required"] is True and view["reference_verified"] is False
    assert view["image_url"] is None and view["market_value_minor"] is None
    assert view["source_attribution"]["label"] == "Card Collector Capital · CC BY 4.0"


def test_source_order_and_name_edits_do_not_change_number_identity():
    source = payload(2)
    original = heritage.normalize_topps_heritage(source)
    source["cards"].reverse()
    assert heritage.normalize_topps_heritage(source) == original
    source["cards"][0]["subjects"] = ["Source corrected spelling"]
    assert [r["provider_id"] for r in heritage.normalize_topps_heritage(source)] == [
        r["provider_id"] for r in original]


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_card_numbers_fail_closed(conflicting):
    source = payload()
    source["cards"].append(deepcopy(source["cards"][0]))
    if conflicting:
        source["cards"][1]["subjects"] = ["Different Player"]
    with pytest.raises(sources.SourceError, match="Duplicate"):
        heritage.normalize_topps_heritage(source)


@pytest.mark.parametrize("change", [
    lambda p: p.update(title="Unreviewed set"),
    lambda p: p.update(reviewedDate="2026-11-04"),
    lambda p: p.update(sourceUrl="https://127.0.0.1/private"),
    lambda p: p.update(sourceSha256="b" * 64),
    lambda p: p.update(license="https://example.invalid/changed"),
    lambda p: p.update(creator="Other"),
    lambda p: p.update(count=True),
    lambda p: p.update(count=101),
    lambda p: p.update(cards=[]),
    lambda p: p.update(cards=[None]),
    lambda p: p["cards"][0].update(number=True),
    lambda p: p["cards"][0].update(number="1"),
    lambda p: p["cards"][0].update(number=0),
    lambda p: p["cards"][0].update(number=401),
    lambda p: p["cards"][0].update(category="Guessed Parallel"),
    lambda p: p["cards"][0].update(category="Quad Rookies"),
    lambda p: p["cards"][0].update(subjects=[]),
    lambda p: p["cards"][0].update(subjects="Player"),
    lambda p: p["cards"][0].update(subjects=[""]),
    lambda p: p["cards"][0].update(subjects=["Name\nInjected"]),
    lambda p: p["cards"][0].update(subjects=["Name\u200bHidden"]),
    lambda p: p["cards"][0].update(sourcePages=[]),
    lambda p: p["cards"][0].update(sourcePages=[True]),
    lambda p: p["cards"][0].update(sourcePages=[0]),
    lambda p: p["cards"][0].update(sourcePages=[9]),
    lambda p: p["cards"][0].update(sourcePages=[1, 1]),
    lambda p: p["cards"][0].update(note="Inferred print run"),
    lambda p: p["cards"][0].update(number=360, subjects=["Owen Caissie"]),
    lambda p: p["cards"][0].update(number=360, note=heritage._BACK_VARIATION_NOTE),
])
def test_invalid_version_identity_or_evidence_is_rejected(change):
    source = payload()
    change(source)
    with pytest.raises(sources.SourceError):
        heritage.normalize_topps_heritage(source)


def test_duplicate_multi_player_subject_is_rejected():
    source = payload()
    source["cards"][0].update(category="Quad Rookies", subjects=["One", "Two", "Three", "One"])
    with pytest.raises(sources.SourceError, match="Duplicate"):
        heritage.normalize_topps_heritage(source)


@pytest.mark.parametrize("language", ["Japanese", "French", "Not applicable", None])
def test_catalogue_translation_is_not_physical_language_evidence(language):
    with pytest.raises(sources.SourceError):
        heritage.normalize_topps_heritage(payload(), language)
    with pytest.raises(sources.SourceError):
        sources.source_descriptor(heritage.PROVIDER, language)


def test_row_and_combined_subject_bounds_are_enforced():
    with pytest.raises(sources.SourceError, match="oversized"):
        heritage.normalize_topps_heritage(payload(101))
    source = payload()
    source["cards"][0].update(category="Quad Rookies", subjects=[str(i) * 100 for i in range(4)])
    with pytest.raises(sources.SourceError, match="combined subjects"):
        heritage.normalize_topps_heritage(source)


@pytest.mark.asyncio
async def test_network_is_one_bounded_public_get_with_digest_and_complete_count(monkeypatch):
    content = fixture_bytes(monkeypatch)
    requests = []
    async def handler(request):
        requests.append(request)
        assert str(request.url) == heritage.DOWNLOAD_URL
        assert request.headers["Accept-Encoding"] == "identity"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=content, headers={"Content-Type": "application/json"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await heritage.fetch_topps_heritage(client, descriptor())
    assert len(requests) == 1 and result.record_count == 100
    assert result.source_sha256 == hashlib.sha256(content).hexdigest()
    assert result.source_revision == "sha256:" + result.source_sha256
    assert result.provider == heritage.PROVIDER and result.system_code == heritage.SYSTEM_CODE


@pytest.mark.asyncio
async def test_changed_export_needs_review_even_with_same_shape_count_and_provenance():
    assert heritage.REVIEWED_EXPORT_SHA256 == "cb37f288a573533e6be0ebb8229dcf34d6d78f419018044447ed52aedcc226bd"
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload(100)))) as client:
        with pytest.raises(sources.SourceError, match="changed; source review"):
            await heritage.fetch_topps_heritage(client, descriptor())


@pytest.mark.asyncio
async def test_incomplete_export_cannot_publish_as_a_successful_subset(monkeypatch):
    content = fixture_bytes(monkeypatch, payload())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=content, headers={"Content-Type": "application/json"}))) as client:
        with pytest.raises(sources.SourceError, match="Incomplete"):
            await heritage.fetch_topps_heritage(client, descriptor())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"download_url": "https://127.0.0.1/"}, {"source_url": "https://example.com/"},
    {"provider": bowman.PROVIDER}, {"system_code": "POKEMON"}, {"source_revision": "unreviewed"},
    {"permission_ref": "https://example.com/"}, {"permission_status": "REVIEW_REQUIRED"},
    {"max_bytes": heritage.MAX_BYTES + 1}, {"catalogue_language": "Japanese"},
])
async def test_descriptor_cannot_expand_the_reviewed_target_or_permissions(change):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(sources.SourcePermissionError):
            await heritage.fetch_topps_heritage(client, replace(descriptor(), **change))
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", [
    {"headers": {"Authorization": "test-only"}}, {"headers": {"X-API-Key": "test-only"}},
    {"cookies": {"session": "test-only"}}, {"params": {"api_key": "test-only"}},
    {"auth": ("test-only", "test-only")},
])
async def test_public_source_client_cannot_carry_credentials(configuration):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **configuration) as client:
        with pytest.raises(sources.SourceError, match="credential-free"):
            await heritage.fetch_topps_heritage(client, descriptor())
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 307, 401, 403, 429, 500, 503])
async def test_redirects_denials_and_transport_statuses_are_not_retried(status):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "http://127.0.0.1/private"},
            text="Private upstream detail")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(sources.SourceError, match=f"HTTP {status}") as error:
            await heritage.fetch_topps_heritage(client, descriptor())
    assert len(calls) == 1 and "Private upstream detail" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b'{"cards":[],"cards":[]}', b'{"cards":NaN}', b'\xff', b'{'])
async def test_invalid_json_is_rejected_before_normalization(monkeypatch, content):
    fixture_bytes(monkeypatch, content=content)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=content, headers={"Content-Type": "application/json"}))) as client:
        with pytest.raises(sources.SourceError, match="source JSON"):
            await heritage.fetch_topps_heritage(client, descriptor())


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {"Content-Encoding": "gzip"}, {"Content-Length": str(heritage.MAX_BYTES + 1)},
    {"Content-Type": "text/html"},
])
async def test_encoded_oversized_or_non_json_response_is_rejected_without_reading(headers):
    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("Rejected body must not be read")
            yield b""
    response = httpx.Response(200, stream=ForbiddenBody(),
        headers={"Content-Type": "application/json", **headers})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(sources.SourceError):
            await heritage.fetch_topps_heritage(client, descriptor())


@pytest.mark.asyncio
async def test_opt_in_dispatch_uses_separate_partition_without_changing_bowman(monkeypatch):
    assert sources.source_descriptor(heritage.PROVIDER) == descriptor()
    assert sources.source_descriptor(bowman.PROVIDER) == sources.SourceDescriptor(
        bowman.PROVIDER, bowman.SYSTEM_CODE, bowman.DOWNLOAD_URL, bowman.SOURCE_REVISION,
        bowman.PERMISSION_REF, "METADATA_ACCESS_DOCUMENTED", bowman.DOWNLOAD_URL, bowman.MAX_BYTES)
    content = fixture_bytes(monkeypatch)
    handler = AsyncMock(return_value=httpx.Response(200, content=content,
        headers={"Content-Type": "application/json"}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(sources.SourcePermissionError):
            await sources.fetch_source(heritage.PROVIDER, client)
        handler.assert_not_called()
        result = await sources.fetch_source(heritage.PROVIDER, client,
            approved_sources={heritage.PROVIDER})
    assert result.record_count == 100 and handler.await_count == 1


def test_worker_configuration_is_opt_in_additive_and_weekly(monkeypatch):
    monkeypatch.delenv("TCG_R2_FIRST_IMPORT_SOURCES", raising=False)
    assert worker.configured_sources() == ()
    monkeypatch.setenv("TCG_R2_FIRST_IMPORT_SOURCES",
        "cardcollectorcapital,cardcollectorcapital_heritage,cardcollectorcapital_heritage")
    assert worker.configured_sources() == (bowman.PROVIDER, heritage.PROVIDER)
    assert worker.SOURCE_REFRESH_SECONDS[heritage.PROVIDER] == 604800
    assert worker.SOURCE_REFRESH_SECONDS[bowman.PROVIDER] == 604800
    for source in (bowman.PROVIDER, heritage.PROVIDER):
        declared = sources.source_descriptor(source)
        worker._permission({"provider": declared.provider, "system_code": declared.system_code,
            "language": declared.catalogue_language, "source_url": declared.source_url,
            "permission_ref": declared.permission_ref})
    with pytest.raises(sources.SourcePermissionError):
        worker._permission({"provider": heritage.PROVIDER, "system_code": heritage.SYSTEM_CODE,
            "language": "English", "source_url": bowman.DOWNLOAD_URL,
            "permission_ref": heritage.PERMISSION_REF})


@pytest.mark.asyncio
async def test_current_heritage_generation_returns_without_http_or_object_writes(monkeypatch):
    old = {"active": True, "published_at": datetime.now(timezone.utc) - timedelta(days=6),
        "record_count": 100, "manifest_sha256": "c" * 64, "generation": 3}
    db = SimpleNamespace(fetchval=AsyncMock(return_value=True), fetchrow=AsyncMock(return_value=old))
    @asynccontextmanager
    async def connection(pool, actor, operation):
        assert actor == ACTOR and operation == "r2-first-import-preflight"
        yield db
    monkeypatch.setattr(worker, "user_connection", connection)
    monkeypatch.setattr(worker, "require_platform_admin", AsyncMock())
    monkeypatch.setenv("TCG_R2_FIRST_IMPORT_SOURCES", heritage.PROVIDER)
    fetch, publish = AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker, "fetch_source", fetch)
    monkeypatch.setattr(worker, "publish_verified", publish)
    result = await worker.import_source(None, ACTOR, heritage.PROVIDER)
    assert result == {"status": "CURRENT", "source": heritage.PROVIDER, "record_count": 100,
        "manifest_sha256": "c" * 64, "generation": 3}
    assert db.fetchrow.call_args.args[1:] == (heritage.PROVIDER, "SPORTS_CARDS", "English")
    fetch.assert_not_awaited()
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_codec_roundtrip_retains_notes_multi_subjects_and_stable_keys():
    class MemoryStore:
        def __init__(self):
            self.objects = {}
        def put_verified_reference_snapshot(self, raw):
            digest = hashlib.sha256(raw).hexdigest()
            self.objects[digest] = raw
            return {"sha256": digest, "verified": True}
        def read_verified_reference_snapshot(self, digest):
            return self.objects[digest]
    source = payload(2)
    source["cards"][0].update(number=360, subjects=["Owen Caissie"], sourcePages=[7],
        note=heritage._BACK_VARIATION_NOTE)
    source["cards"][1].update(number=376, category="Quad Rookies", sourcePages=[1, 2],
        subjects=["Fixture One", "Fixture Two", "Fixture Three", "Fixture Four"])
    rows = heritage.normalize_topps_heritage(source)
    args = dict(provider=heritage.PROVIDER, system_code=heritage.SYSTEM_CODE,
        language="English", source_url=heritage.DOWNLOAD_URL,
        source_revision=heritage.SOURCE_REVISION, permission_ref=heritage.PERMISSION_REF)
    bundle = codec.prepare_catalogue(rows, **args)
    assert codec.prepare_catalogue(rows, **args).manifest == bundle.manifest
    store = MemoryStore()
    manifest = await codec.upload_and_verify(bundle, store)
    snapshot = await codec.load_catalogue(manifest, store)
    try:
        assert snapshot.search(limit=1)["total"] == 2
        assert snapshot.search(q="Fixture Four")["total"] == 1
        assert snapshot.sets()[0]["count"] == 2
        row, = snapshot.search(q="Owen Caissie")["items"]
        assert row["details"]["source_note"] == heritage._BACK_VARIATION_NOTE
        assert row["details"]["source_license"] == heritage.SOURCE_LICENSE
        assert snapshot.get(row["key"]) == row
        assert "market_value" not in row and "image_url" not in row
    finally:
        snapshot.close()
