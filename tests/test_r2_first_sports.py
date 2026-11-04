"""Synthetic checklist fixtures and bounded mocked HTTP; no production writes."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app import r2_first_sources as sources
from app import r2_first_sports as sports
from app import r2_first_catalogue as codec


def payload(count=1):
    rows = []
    for index in range(1, count + 1):
        rows.append({
            "id": f"2026-bowman-baseball-paper-prospects-bp-{index}-fixture-player-2",
            "year": 2026, "product": "Bowman Baseball", "releaseStatus": "Released",
            "cardCode": f"BP-{index}", "player": "Fixture Player", "team": "Fixture Team",
            "family": "Paper prospect", "checklistSection": "Paper Prospects", "sourcePage": 2,
            "sourceUrl": sports._PRODUCTS[(2026, "Bowman Baseball")].evidence_url,
            "productUrl": "https://www.topps.com/pages/bowman-baseball",
            "reviewedDate": sports.SOURCE_REVIEWED_DATE,
            "image": "https://private.invalid/do-not-fetch", "price": 9999,
            "owner_id": "private-owner", "description": "Unlicensed prose must not leave adapter",
        })
    return {"license": sports.SOURCE_LICENSE, "creator": sports.SOURCE_CREDIT,
        "reviewedDate": sports.SOURCE_REVIEWED_DATE, "records": rows}


def descriptor():
    return sources.SourceDescriptor(sports.PROVIDER, sports.SYSTEM_CODE,
        sports.DOWNLOAD_URL, sports.SOURCE_REVISION, sports.PERMISSION_REF,
        "METADATA_ACCESS_DOCUMENTED", sports.DOWNLOAD_URL, sports.MAX_BYTES)


def test_only_whitelisted_facts_and_attribution_leave_adapter():
    source = payload()
    original = deepcopy(source)
    record, = sports.normalize_sports(source)
    assert source == original
    assert record == sports.normalize_sports(source)[0]
    assert set(record) == sources.NORMALIZED_FIELDS | {"details"}
    assert record["provider_id"] == source["records"][0]["id"]
    assert record["name"] == "Fixture Player"
    assert record["set_name"] == "2026 Bowman Baseball" and record["card_number"] == "BP-1"
    assert record["product_type"] == "CARD" and record["system_code"] == "SPORTS_CARDS"
    assert record["rarity"] is record["finish"] is record["release_date"] is None
    details = record["details"]
    assert details["source_evidence_url"] == source["records"][0]["sourceUrl"]
    assert details["source_reviewed_at"] == sports.SOURCE_REVIEWED_DATE
    assert details["source_page"] == "2" and details["source_credit"] == sports.SOURCE_CREDIT
    assert details["source_license"] == sports.SOURCE_LICENSE
    assert details["reference_scope"] == sports.REFERENCE_SCOPE
    assert details["team"] == "Fixture Team" and details["variant"] == "Paper Prospects"
    serialized = json.dumps(record)
    for excluded in ("private.invalid", "private-owner", "Unlicensed prose", '"price"', '"image"'):
        assert excluded not in serialized


def test_unknown_team_is_omitted_not_guessed():
    source = payload()
    source["records"][0]["team"] = None
    record, = sports.normalize_sports(source)
    assert "team" not in record["details"]


def test_source_identity_not_shared_card_code_defines_distinct_references():
    source = payload(2)
    source["records"][1]["cardCode"] = source["records"][0]["cardCode"]
    source["records"][1]["player"] = "Different Player"
    records = sports.normalize_sports(source)
    assert len(records) == 2 and len({row["provider_id"] for row in records}) == 2
    source["records"].reverse()
    assert sports.normalize_sports(source) == records


@pytest.mark.parametrize("conflicting", [False, True])
def test_duplicate_source_id_fails_closed_even_when_content_matches(conflicting):
    source = payload()
    source["records"].append(deepcopy(source["records"][0]))
    if conflicting:
        source["records"][1]["player"] = "Conflict"
    with pytest.raises(sources.SourceError, match="Duplicate"):
        sports.normalize_sports(source)


@pytest.mark.parametrize("change", [
    lambda p: p.update(license="https://example.invalid/unreviewed"),
    lambda p: p.update(creator="Unknown"),
    lambda p: p.update(reviewedDate="2026-10-28"),
    lambda p: p.update(records=[]),
    lambda p: p.update(records=[None]),
    lambda p: p["records"][0].update(year=True),
    lambda p: p["records"][0].update(product="Unreviewed Product"),
    lambda p: p["records"][0].update(id="unrelated-source-id-2"),
    lambda p: p["records"][0].update(id=" " + p["records"][0]["id"]),
    lambda p: p["records"][0].update(sourcePage=True),
    lambda p: p["records"][0].update(sourcePage=3),
    lambda p: p["records"][0].update(sourceUrl="http://127.0.0.1/private"),
    lambda p: p["records"][0].update(productUrl="https://not-followed.invalid/"),
    lambda p: p["records"][0].update(reviewedDate="2026-11-04"),
    lambda p: p["records"][0].update(checklistSection="Guessed Refractor"),
    lambda p: p["records"][0].update(family="Unknown"),
    lambda p: p["records"][0].update(family=[]),
    lambda p: p["records"][0].update(cardCode=""),
    lambda p: p["records"][0].update(player=""),
    lambda p: p["records"][0].update(player="Name\nInjected"),
    lambda p: p["records"][0].update(player="Name\u200bHidden"),
    lambda p: p["records"][0].update(team=[]),
])
def test_invalid_version_identity_or_provenance_is_rejected(change):
    source = payload()
    change(source)
    with pytest.raises(sources.SourceError):
        sports.normalize_sports(source)


@pytest.mark.parametrize("language", ["Japanese", "French", None])
def test_translation_is_not_physical_language_evidence(language):
    with pytest.raises(sources.SourceError):
        sports.normalize_sports(payload(), language)


def test_row_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(sports, "EXPECTED_ROWS", 1)
    with pytest.raises(sources.SourceError, match="oversized"):
        sports.normalize_sports(payload(2))


@pytest.mark.asyncio
async def test_success_is_one_bounded_get_with_complete_count_and_digest():
    content = json.dumps(payload(sports.EXPECTED_ROWS)).encode()
    requests = []
    async def handler(request):
        requests.append(request)
        assert str(request.url) == sports.DOWNLOAD_URL
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Accept-Encoding"] == "identity"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=content, headers={"Content-Type": "application/json"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await sports.fetch_sports(client, descriptor())
    assert len(requests) == 1 and result.record_count == sports.EXPECTED_ROWS
    assert result.source_sha256 == hashlib.sha256(content).hexdigest()
    assert result.source_revision == "sha256:" + result.source_sha256
    assert result.provider == sports.PROVIDER and result.system_code == sports.SYSTEM_CODE
    assert not hasattr(result, "raw") and not hasattr(result, "payload")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"download_url": "https://127.0.0.1/"}, {"source_url": "https://example.com/"},
    {"provider": "other"}, {"system_code": "POKEMON"}, {"source_revision": "unreviewed"},
    {"permission_ref": "https://example.com/"}, {"permission_status": "REVIEW_REQUIRED"},
    {"max_bytes": sports.MAX_BYTES + 1},
])
async def test_descriptor_cannot_select_an_arbitrary_target_or_expand_permissions(change):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(sources.SourcePermissionError):
            await sports.fetch_sports(client, replace(descriptor(), **change))
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", [
    {"headers": {"Authorization": "test-only"}}, {"headers": {"X-API-Key": "test-only"}},
    {"cookies": {"session": "test-only"}}, {"params": {"api_key": "test-only"}},
    {"auth": ("test-only", "test-only")},
])
async def test_public_client_cannot_carry_credentials(configuration):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **configuration) as client:
        with pytest.raises(sources.SourceError, match="credential-free"):
            await sports.fetch_sports(client, descriptor())
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 307, 401, 403, 429, 500, 503])
async def test_errors_do_not_follow_redirects_retry_or_expose_raw_errors(status):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "http://127.0.0.1/private"},
            text="private upstream detail")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(sources.SourceError, match=f"HTTP {status}") as error:
            await sports.fetch_sports(client, descriptor())
    assert len(calls) == 1 and "private upstream detail" not in str(error.value)


@pytest.mark.asyncio
async def test_truncated_versioned_export_is_not_a_successful_subset():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, json=payload()))) as client:
        with pytest.raises(sources.SourceError, match="Incomplete"):
            await sports.fetch_sports(client, descriptor())


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b'{"records":[],"records":[]}', b'{"records":NaN}', b'\xff', b'{'])
async def test_malformed_nonstandard_or_duplicate_json_is_rejected(content):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=content, headers={"Content-Type": "application/json"}))) as client:
        with pytest.raises(sources.SourceError, match="source JSON"):
            await sports.fetch_sports(client, descriptor())


@pytest.mark.asyncio
async def test_encoded_or_oversized_body_is_rejected_before_reading():
    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("Rejected response body must not be read")
            yield b""
    for extra_headers in ({"Content-Encoding": "gzip"}, {"Content-Length": str(sports.MAX_BYTES + 1)}):
        response = httpx.Response(200, stream=ForbiddenBody(),
            headers={"Content-Type": "application/json", **extra_headers})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            with pytest.raises(sources.SourceError):
                await sports.fetch_sports(client, descriptor())


@pytest.mark.asyncio
async def test_public_dispatch_preserves_opt_in_and_fixed_descriptor():
    assert sources.source_descriptor(sports.PROVIDER) == descriptor()
    handler = AsyncMock(return_value=httpx.Response(200, json=payload(sports.EXPECTED_ROWS)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(sources.SourcePermissionError):
            await sources.fetch_source(sports.PROVIDER, client)
        handler.assert_not_called()
        result = await sources.fetch_source(sports.PROVIDER, client,
            approved_sources={sports.PROVIDER})
    assert result.record_count == sports.EXPECTED_ROWS
    assert handler.await_count == 1


@pytest.mark.asyncio
async def test_codec_roundtrip_preserves_provenance_and_search_without_database():
    class MemoryStore:
        def __init__(self):
            self.objects = {}

        def put_verified_reference_snapshot(self, raw):
            digest = hashlib.sha256(raw).hexdigest()
            self.objects[digest] = raw
            return {"sha256": digest, "verified": True}

        def read_verified_reference_snapshot(self, digest):
            return self.objects[digest]

    rows = sports.normalize_sports(payload(2))
    bundle = codec.prepare_catalogue(rows, provider=sports.PROVIDER,
        system_code=sports.SYSTEM_CODE, language="English", source_url=sports.DOWNLOAD_URL,
        source_revision=sports.SOURCE_REVISION, permission_ref=sports.PERMISSION_REF)
    storage = MemoryStore()
    manifest = await codec.upload_and_verify(bundle, storage)
    snapshot = await codec.load_catalogue(manifest, storage)
    try:
        found = snapshot.search(q="Fixture Player")
        assert found["total"] == 2
        assert snapshot.search(q="Fixture Team")["total"] == 2
        assert snapshot.search(product_type="FIGURE")["total"] == 0
        assert snapshot.sets()[0]["count"] == 2
        for row in found["items"]:
            assert row["details"]["source_evidence_url"].endswith("?v=1775743176")
            assert row["details"]["source_credit"] == sports.SOURCE_CREDIT
            assert row["details"]["reference_scope"] == sports.REFERENCE_SCOPE
            assert snapshot.get(row["key"]) == row
            assert "market_value" not in row and "image_url" not in row
    finally:
        snapshot.close()
