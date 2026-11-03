"""Synthetic metadata and mocked HTTP only; no live provider or storage writes."""
from copy import deepcopy
import gzip
import hashlib
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app import r2_first_sources as sources


def ygo():
    return {"data": [{"id": 12345678, "name": "Fixture Dragon", "card_sets": [
        {"set_code": "ABC-EN001", "set_name": "Fixture Set", "set_rarity": "Rare", "set_rarity_code": "R"},
        {"set_code": "ABC-EN001", "set_name": "Fixture Set", "set_rarity": "Ultra Rare", "set_rarity_code": "UR"},
        {"set_code": "XYZ-EN001", "set_name": "Fixture Reprint", "set_rarity": "Rare", "set_rarity_code": "R"},
    ], "card_images": [{"id": 12345678, "image_url": "https://private.invalid/secret"},
                        {"id": 12345679, "image_url": "https://private.invalid/alternate"}],
        "card_prices": [{"ebay_price": "999"}], "owner_id": "private-owner", "raw": "private"}]}


def lorcana():
    return {"metadata": {"language": "en", "formatVersion": "2.4.0",
        "generatedOn": "2026-11-03T12:00:00Z"},
        "sets": {"1": {"name": "Fixture Set", "releaseDate": "2026-01-01"}},
        "cards": [{"id": 1, "setCode": "1", "fullName": "Fixture Mouse - Explorer",
            "fullIdentifier": "1/204 • EN • 1", "number": 1, "rarity": "Rare",
            "foilTypes": ["None", "Cold"], "images": {"full": "https://private.invalid/art"},
            "market_value": 99999}]}


def scryfall():
    return [{"id": "11111111-1111-4111-8111-111111111111", "oracle_id": "same-gameplay-id",
        "name": "Fixture Bolt", "lang": "en", "set": "abc", "set_name": "Fixture Set",
        "collector_number": "123★", "finishes": ["nonfoil", "foil"],
        "rarity": "rare", "released_at": "2026-01-01", "digital": False, "games": ["paper", "mtgo"],
        "image_uris": {"normal": "https://private.invalid/art"}, "prices": {"usd": "12345"},
        "owner_id": "private-owner"}]


@pytest.mark.parametrize("provider,payload", [("ygoprodeck", ygo), ("lorcanajson", lorcana), ("scryfall", scryfall)])
def test_only_allowlisted_metadata_leaves_adapters(provider, payload):
    original = payload()
    before = deepcopy(original)
    records = sources.normalize_source(provider, original)
    assert records == sources.normalize_source(provider, original)
    assert original == before
    assert all(set(row) == sources.NORMALIZED_FIELDS for row in records)
    assert all(row["product_type"] == "CARD" and row["language"] == "English" for row in records)
    serialized = json.dumps(records)
    for secret in ("private.invalid", "private-owner", "image_url", "market_value", "card_prices", '"prices"', '"raw"'):
        assert secret not in serialized
    assert all(row["source_url"].startswith("https://") and "?" not in row["source_url"] for row in records)


def test_ygo_printing_rarity_and_reprint_stay_separate_without_art_cross_product():
    records = sources.normalize_ygoprodeck(ygo())
    assert len(records) == 3
    assert len({row["provider_id"] for row in records}) == 3
    assert {row["rarity"] for row in records} == {"Rare", "Ultra Rare"}
    assert {row["card_number"] for row in records} == {"ABC-EN001", "XYZ-EN001"}
    assert all(row["finish"] is None and row["release_date"] is None for row in records)
    payload = ygo()
    payload["data"][0]["card_images"] = [{"id": 9}] * 1000
    assert sources.normalize_ygoprodeck(payload) == records


def test_ygo_no_printing_is_incomplete_reference_not_invented_set():
    payload = {"data": [{"id": 12345678, "name": "Fixture Card"}]}
    row, = sources.normalize_ygoprodeck(payload)
    assert row["set_id"] == row["set_name"] == row["card_number"] == ""
    assert row["rarity"] is row["finish"] is row["release_date"] is None


def test_ygo_stable_order_and_identical_duplicates_are_idempotent():
    original = ygo()
    result = sources.normalize_ygoprodeck(original)
    original["data"][0]["card_sets"].reverse()
    original["data"] += deepcopy(original["data"])
    assert sources.normalize_ygoprodeck(original) == result


def test_ygo_conflicting_same_identity_fails_closed():
    payload = ygo()
    payload["data"].append(deepcopy(payload["data"][0]))
    payload["data"][1]["name"] = "Conflicting Name"
    with pytest.raises(sources.SourceError, match="Conflicting"):
        sources.normalize_ygoprodeck(payload)


@pytest.mark.parametrize("change", [
    lambda p: p.update(error="private error text"),
    lambda p: p.update(meta={"next_page": "https://not-followed.invalid/"}),
    lambda p: p.update(meta={"total_rows": 20}),
    lambda p: p["data"][0].update(id=True),
    lambda p: p["data"][0].update(id=-1),
    lambda p: p["data"][0].update(name="Name\nInjected line"),
    lambda p: p["data"][0].update(card_sets="not-an-array"),
    lambda p: p["data"][0].update(card_sets=[{}]),
    lambda p: p["data"][0]["card_sets"][0].update(set_code=None),
])
def test_ygo_malformed_or_partial_payloads_fail_closed(change):
    payload = ygo()
    change(payload)
    with pytest.raises(sources.SourceError):
        sources.normalize_ygoprodeck(payload)


@pytest.mark.parametrize("language", ["Japanese", "French", "Portuguese", "Unknown", None])
def test_ygo_localized_names_are_not_physical_printing_language_proof(language):
    with pytest.raises(sources.SourceError):
        sources.normalize_ygoprodeck(ygo(), language)


def test_lorcana_explicit_finishes_and_alternate_ids_are_not_merged():
    payload = lorcana()
    alternate = deepcopy(payload["cards"][0])
    alternate["id"] = 2
    alternate["fullIdentifier"] = "1a/204 • EN • 1"
    payload["cards"].append(alternate)
    result = sources.normalize_lorcanajson(payload)
    assert len(result) == len({row["provider_id"] for row in result}) == 4
    assert {row["finish"] for row in result} == {"None", "Cold"}
    assert {row["card_number"] for row in result} == {"1/204", "1a/204"}
    assert all(row["release_date"] == "2026-01-01" for row in result)


def test_lorcana_unknown_finish_remains_null_and_null_number_is_supported():
    payload = lorcana()
    payload["cards"][0].pop("foilTypes")
    payload["cards"][0].pop("fullIdentifier")
    payload["cards"][0]["number"] = None
    row, = sources.normalize_lorcanajson(payload)
    assert row["finish"] is None and row["card_number"] == ""


def test_lorcana_same_id_other_language_remains_different_reference():
    english = sources.normalize_lorcanajson(lorcana())
    payload = lorcana()
    payload["metadata"]["language"] = "fr"
    payload["cards"][0]["fullIdentifier"] = "1/204 • FR • 1"
    french = sources.normalize_lorcanajson(payload, "French")
    assert {row["provider_id"] for row in english}.isdisjoint(row["provider_id"] for row in french)
    assert all(row["language"] == "French" for row in french)


@pytest.mark.parametrize("change", [
    lambda p: p["metadata"].update(language="fr"),
    lambda p: p["metadata"].update(formatVersion="3.0.0"),
    lambda p: p["metadata"].update(generatedOn="not-a-date"),
    lambda p: p["cards"][0].update(fullIdentifier="1/204 • FR • 1"),
    lambda p: p["cards"][0].update(fullIdentifier="1/204"),
    lambda p: p.update(sets={}),
    lambda p: p["cards"][0].update(foilTypes=[]),
    lambda p: p["cards"][0].update(foilTypes="Cold"),
    lambda p: p["sets"]["1"].update(releaseDate="2026-02-30"),
])
def test_lorcana_schema_language_and_dates_fail_closed(change):
    payload = lorcana()
    change(payload)
    with pytest.raises(sources.SourceError):
        sources.normalize_lorcanajson(payload)


def test_scryfall_printing_uuid_and_finish_not_oracle_id_define_identity():
    payload = scryfall()
    reprint = deepcopy(payload[0])
    reprint.update(id="22222222-2222-4222-8222-222222222222", set="xyz", set_name="Reprint")
    payload.append(reprint)
    result = sources.normalize_scryfall(payload)
    assert len(result) == len({row["provider_id"] for row in result}) == 4
    assert {row["finish"] for row in result} == {"foil", "nonfoil"}
    assert all(row["card_number"] == "123★" for row in result)


def test_scryfall_digital_and_nonmatching_languages_are_not_relabelled():
    payload = scryfall()
    for changes in ({"digital": True}, {"games": ["arena"]}, {"lang": "ja"}):
        payload.append({**deepcopy(payload[0]), **changes})
    assert sources.normalize_scryfall(payload) == sources.normalize_scryfall(scryfall())
    japanese = sources.normalize_scryfall(payload, "Japanese")
    assert all(row["language"] == "Japanese" and row["name"] == "Fixture Bolt" for row in japanese)


def test_scryfall_unknown_finish_not_inferred_from_price_or_old_boolean():
    payload = scryfall()
    payload[0].pop("finishes")
    payload[0]["foil"] = True
    row, = sources.normalize_scryfall(payload)
    assert row["finish"] is None


@pytest.mark.parametrize("change", [
    lambda p: p[0].update(id="not-a-uuid"),
    lambda p: p[0].update(lang=None),
    lambda p: p[0].update(digital="false"),
    lambda p: p[0].update(games=None),
    lambda p: p[0].update(released_at="tomorrow"),
    lambda p: p[0].update(finishes=[]),
])
def test_scryfall_invalid_physical_identity_is_rejected(change):
    payload = scryfall()
    change(payload)
    with pytest.raises(sources.SourceError):
        sources.normalize_scryfall(payload)


@pytest.mark.parametrize("source", ["ygoprodeck", "lorcanajson", "scryfall", "riftcodex"])
def test_source_descriptors_are_explicit_frozen_and_do_not_claim_art_rights(source):
    descriptor = sources.source_descriptor(source)
    assert descriptor.provider == source
    assert descriptor.source_url.startswith("https://") and "?" not in descriptor.source_url
    assert descriptor.permission_ref.startswith("https://") and descriptor.source_revision
    assert descriptor.max_bytes == sources.MAX_SOURCE_BYTES
    if source == "ygoprodeck":
        assert descriptor.permission_status == "METADATA_ACCESS_DOCUMENTED"
    elif source == "riftcodex":
        assert descriptor.permission_status == "DEFERRED" and descriptor.download_url is None
    else:
        assert descriptor.permission_status == "REVIEW_REQUIRED"


@pytest.mark.parametrize("source", ["https://127.0.0.1/", "unknown", "YGOPRODECK"])
def test_arbitrary_source_or_url_is_not_accepted(source):
    with pytest.raises(sources.SourceError, match="Unknown"):
        sources.source_descriptor(source)


@pytest.mark.asyncio
async def test_fetch_opt_in_is_required_before_any_network_call():
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for approved in ((), "ygoprodeck", {"other"}):
            with pytest.raises(sources.SourcePermissionError):
                await sources.fetch_source("ygoprodeck", client, approved_sources=approved)
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["lorcanajson", "scryfall", "riftcodex"])
async def test_unverified_rights_are_not_enabled_by_merely_passing_a_name(source):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises((sources.SourcePermissionError, sources.DeferredSourceError)):
            await sources.fetch_source(source, client, approved_sources={source})
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_has_one_bounded_get_and_returns_no_raw_payload():
    content = json.dumps(ygo()).encode()
    requests = []
    async def handler(request):
        requests.append(request)
        assert str(request.url) == "https://db.ygoprodeck.com/api/v7/cardinfo.php"
        assert request.headers["User-Agent"].startswith("DropRateMetadataImport/")
        assert request.headers["Accept"] == "application/json"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=content, headers={"content-type": "application/json"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await sources.fetch_source("ygoprodeck", client, approved_sources={"ygoprodeck"})
    assert len(requests) == 1 and result.record_count == 3
    assert result.source_sha256 == hashlib.sha256(content).hexdigest()
    assert result.source_revision == "sha256:" + result.source_sha256
    assert result.records == sources.normalize_ygoprodeck(ygo())
    assert not hasattr(result, "payload") and not hasattr(result, "raw")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 307, 400, 401, 403, 429, 500, 503])
async def test_provider_errors_and_redirects_do_not_retry_or_follow(status):
    calls = []
    async def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "http://127.0.0.1/private"}, text="private provider error")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(sources.SourceError, match=f"HTTP {status}") as error:
            await sources.fetch_source("ygoprodeck", client, approved_sources={"ygoprodeck"})
    assert len(calls) == 1 and "private provider error" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", [
    {"headers": {"Authorization": "test-only"}},
    {"headers": {"X-Api-Key": "test-only"}},
    {"cookies": {"session": "test-only"}},
    {"auth": ("test-only", "test-only")},
    {"params": {"api_key": "test-only"}},
])
async def test_public_source_client_must_not_carry_credentials(configuration):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **configuration) as client:
        with pytest.raises(sources.SourceError, match="credential-free"):
            await sources.fetch_source("ygoprodeck", client, approved_sources={"ygoprodeck"})
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["length", "chunked", "compressed"])
async def test_both_advertised_and_decoded_payload_size_are_bounded(monkeypatch, mode):
    descriptor = sources.source_descriptor("ygoprodeck")
    from dataclasses import replace
    monkeypatch.setattr(sources, "source_descriptor", lambda *_: replace(descriptor, max_bytes=32))
    content = b" " * 1000
    headers = {"content-type": "application/json"}
    if mode == "compressed":
        content = gzip.compress(content)
        headers["content-encoding"] = "gzip"
    response = httpx.Response(200, content=content, headers=headers)
    if mode == "chunked":
        response.headers.pop("content-length", None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(sources.SourceError, match="byte bound"):
            await sources.fetch_source("ygoprodeck", client, approved_sources={"ygoprodeck"})


@pytest.mark.asyncio
async def test_encoded_body_is_rejected_before_any_decoder_can_expand_it():
    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("Encoded bytes must not be consumed")
            yield b""  # Defines an async iterator; it must never execute.

    response = httpx.Response(200, stream=ForbiddenBody(), headers={
        "content-type": "application/json", "content-encoding": "gzip"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(sources.SourceError, match="Encoded response"):
            await sources.fetch_source("ygoprodeck", client, approved_sources={"ygoprodeck"})


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b'{"data":[],"data":[]}', b'{"data":NaN}', b'{"data":', b'\xff'])
async def test_invalid_duplicate_or_nonstandard_json_is_rejected(content):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=content, headers={"content-type": "application/json"}))) as client:
        with pytest.raises(sources.SourceError, match="source JSON"):
            await sources.fetch_source("ygoprodeck", client, approved_sources={"ygoprodeck"})


@pytest.mark.asyncio
async def test_transport_timeout_fails_without_retry():
    calls = 0
    async def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("test-only", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(sources.SourceError, match="transport failed"):
            await sources.fetch_source("ygoprodeck", client, approved_sources={"ygoprodeck"})
    assert calls == 1


@pytest.mark.parametrize("url", [
    "http://data.scryfall.io/default-cards/default-cards-20261103120000.json",
    "https://data.scryfall.io.evil.invalid/default-cards/default-cards-20261103120000.json",
    "https://user:password@data.scryfall.io/default-cards/default-cards-20261103120000.json",
    "https://data.scryfall.io:443/default-cards/default-cards-20261103120000.json",
    "https://data.scryfall.io/default-cards/default-cards-20261103120000.json?secret=1",
    "https://data.scryfall.io/default-cards/default-cards-20261103120000.json#fragment",
    "https://data.scryfall.io/other-data/default-cards-20261103120000.json",
])
def test_scryfall_descriptor_cannot_supply_arbitrary_download_targets(url):
    with pytest.raises(sources.SourceError, match="Unapproved"):
        sources._scryfall_bulk_url({"object": "bulk_data", "type": "default_cards", "size": 100, "download_uri": url})


def test_scryfall_large_bulk_is_not_loaded_into_memory():
    with pytest.raises(sources.SourceError, match="streaming importer"):
        sources._scryfall_bulk_url({"object": "bulk_data", "type": "default_cards", "size": 600_000_000,
            "download_uri": "https://data.scryfall.io/default-cards/default-cards-20261103120000.json"})


def test_normalized_row_bound_is_checked(monkeypatch):
    monkeypatch.setattr(sources, "MAX_NORMALIZED_ROWS", 2)
    with pytest.raises(sources.SourceError, match="Oversized"):
        sources.normalize_ygoprodeck(ygo())


def test_riftcodex_is_explicitly_deferred_not_an_empty_success():
    with pytest.raises(sources.DeferredSourceError, match="deferred"):
        sources.normalize_source("riftcodex", {"items": []})
