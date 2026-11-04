"""Synthetic Lorcast metadata and mocked HTTP; no storage or provider writes."""
from copy import deepcopy
from dataclasses import replace
import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app import r2_first_lorcast as lorcast
from app.r2_first_sources import NORMALIZED_FIELDS, SourceDescriptor, SourceError, SourcePermissionError


def fixture_bundle():
    sets = [
        {"id": "set_" + "a" * 32, "code": "1", "name": "Fixture Set",
         "released_at": "2026-01-01", "prereleased_at": "2025-12-20"},
        {"id": "set_" + "b" * 32, "code": "P1", "name": "Fixture Promo",
         "released_at": "2026-02-01", "prereleased_at": "2026-01-20"},
    ]
    cards_by_set = {}
    for index, source_set in enumerate(sets):
        cards_by_set[source_set["id"]] = [{
            "id": "crd_" + str(index + 1) * 32,
            "name": "Fixture Mouse", "version": "Explorer", "lang": "en",
            "collector_number": "001★" if index == 0 else "P-01",
            "rarity": "Rare", "released_at": source_set["released_at"],
            "set": {key: source_set[key] for key in ("id", "code", "name")},
            "image_uris": {"digital": {"normal": "https://private.invalid/art"}},
            "text": "private rules text", "flavor_text": "private flavour text",
            "prices": {"usd_foil": "10000"}, "owner_id": "private owner",
        }]
    return {"sets": sets, "cards_by_set": cards_by_set}


def first_card(bundle):
    return bundle["cards_by_set"][bundle["sets"][0]["id"]][0]


def descriptor():
    return SourceDescriptor(
        "lorcast", "DISNEY_LORCANA", lorcast.LORCAST_SETS_URL,
        "api-v0-english-metadata-v1", "https://lorcast.com/docs/api",
        "METADATA_ACCESS_DOCUMENTED", lorcast.LORCAST_SETS_URL,
    )


def route_payloads(bundle):
    return {
        lorcast.LORCAST_SETS_URL: {"results": bundle["sets"]},
        **{lorcast.LORCAST_SETS_URL + "/" + identifier + "/cards": cards
           for identifier, cards in bundle["cards_by_set"].items()},
    }


def json_response(payload, **headers):
    return httpx.Response(200, content=json.dumps(payload).encode(),
                          headers={"content-type": "application/json", **headers})


def test_whitelisted_factual_metadata_only_and_input_unchanged():
    bundle = fixture_bundle()
    original = deepcopy(bundle)
    records = lorcast.normalize_lorcast(bundle)
    assert bundle == original
    assert records == lorcast.normalize_lorcast(bundle)
    assert len(records) == 2
    assert all(set(row) == NORMALIZED_FIELDS for row in records)
    assert all(row["provider"] == "lorcast" and row["system_code"] == "DISNEY_LORCANA"
               and row["language"] == "English" and row["product_type"] == "CARD" for row in records)
    assert all(row["name"] == "Fixture Mouse - Explorer" and row["finish"] is None for row in records)
    assert records[0]["provider_id"] == "lorcast:crd_" + "1" * 32
    assert records[0]["set_id"] == "1" and records[0]["card_number"] == "001★"
    assert records[0]["source_url"] == lorcast.LORCAST_SETS_URL + "/set_" + "a" * 32 + "/cards"
    for excluded in ("private.invalid", "private rules", "private flavour", "private owner",
                     "prices", "image_uris", "10000", "owner_id"):
        assert excluded not in json.dumps(records)


def test_source_printing_id_and_version_not_name_define_identity():
    bundle = fixture_bundle()
    original = first_card(bundle)
    alternate = deepcopy(original)
    alternate["id"] = "crd_" + "3" * 32
    alternate["version"] = "Navigator"
    bundle["cards_by_set"][bundle["sets"][0]["id"]].append(alternate)
    rows = lorcast.normalize_lorcast(bundle)
    assert len(rows) == len({row["provider_id"] for row in rows}) == 3
    assert {row["name"] for row in rows} == {"Fixture Mouse - Explorer", "Fixture Mouse - Navigator"}


def test_unknown_number_finish_and_card_release_are_not_invented():
    bundle = fixture_bundle()
    first_card(bundle).update(version=None, collector_number=None, released_at=None,
                             foil=True, image_uris={"foil": "private"})
    row = lorcast.normalize_lorcast(bundle)[0]
    assert row["name"] == "Fixture Mouse" and row["card_number"] == ""
    assert row["finish"] is row["release_date"] is None


def test_non_english_cards_are_excluded_not_relabelled():
    bundle = fixture_bundle()
    foreign = deepcopy(first_card(bundle))
    foreign.update(id="crd_" + "f" * 32, lang="fr", name="Foreign fixture")
    bundle["cards_by_set"][bundle["sets"][0]["id"]].append(foreign)
    rows = lorcast.normalize_lorcast(bundle)
    assert len(rows) == 2 and all(row["language"] == "English" for row in rows)
    assert all(row["name"] != "Foreign fixture" for row in rows)


@pytest.mark.parametrize("language", ["French", "fr", "Japanese", None, "unknown"])
def test_other_import_languages_fail_closed(language):
    with pytest.raises(SourceError):
        lorcast.normalize_lorcast(fixture_bundle(), language)


def test_idempotent_order_and_identical_duplicate_rows():
    bundle = fixture_bundle()
    expected = lorcast.normalize_lorcast(bundle)
    bundle["sets"].reverse()
    cards = bundle["cards_by_set"][bundle["sets"][0]["id"]]
    cards.extend(deepcopy(cards))
    assert lorcast.normalize_lorcast(bundle) == expected


def test_conflicting_provider_id_fails_instead_of_overwriting():
    bundle = fixture_bundle()
    conflicting = deepcopy(first_card(bundle))
    conflicting["name"] = "Conflicting fixture"
    bundle["cards_by_set"][bundle["sets"][0]["id"]].append(conflicting)
    with pytest.raises(SourceError, match="Conflicting"):
        lorcast.normalize_lorcast(bundle)


@pytest.mark.parametrize("change", [
    lambda b: b.update(sets=[]),
    lambda b: b.update(cards_by_set={}),
    lambda b: b.update(next_page="https://private.invalid"),
    lambda b: b["sets"].append(deepcopy(b["sets"][0])),
    lambda b: b["sets"][1].update(code="1"),
    lambda b: b["sets"][0].update(id="../../private"),
    lambda b: b["sets"][0].update(code="../private"),
    lambda b: b["sets"][0].update(released_at="2026-02-30"),
    lambda b: b["cards_by_set"].update(extra=[]),
    lambda b: b["cards_by_set"].update({b["sets"][0]["id"]: []}),
    lambda b: b["cards_by_set"].update({b["sets"][0]["id"]: {"results": []}}),
    lambda b: first_card(b).update(id="crd_../private"),
    lambda b: first_card(b).update(name="Invalid\nname"),
    lambda b: first_card(b).update(version={"injected": "value"}),
    lambda b: first_card(b).update(collector_number=True),
    lambda b: first_card(b).pop("collector_number"),
    lambda b: first_card(b).update(lang=None),
    lambda b: first_card(b).update(lang="unknown"),
    lambda b: first_card(b).update(released_at="tomorrow"),
    lambda b: first_card(b).update(rarity=[]),
    lambda b: first_card(b)["set"].update(id="set_" + "b" * 32),
    lambda b: first_card(b)["set"].update(code="P1"),
    lambda b: first_card(b)["set"].update(name="Unexpected"),
])
def test_malformed_or_incomplete_identity_fails_closed(change):
    bundle = fixture_bundle()
    change(bundle)
    with pytest.raises(SourceError):
        lorcast.normalize_lorcast(bundle)


@pytest.mark.parametrize("bound,value", [
    ("MAX_REQUESTS", 2), ("MAX_CARDS_PER_SET", 0), ("MAX_TOTAL_CARDS", 1),
])
def test_offline_bounds(monkeypatch, bound, value):
    monkeypatch.setattr(lorcast, bound, value)
    with pytest.raises(SourceError):
        lorcast.normalize_lorcast(fixture_bundle())


@pytest.fixture
def no_rate_wait(monkeypatch):
    pause = AsyncMock()
    monkeypatch.setattr(lorcast.asyncio, "sleep", pause)
    return pause


@pytest.mark.asyncio
async def test_fetch_all_sets_sequentially_without_credentials_and_with_spacing(no_rate_wait):
    bundle = fixture_bundle()
    routes = route_payloads(bundle)
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        assert "cookie" not in request.headers and "authorization" not in request.headers
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Accept-Encoding"] == "identity"
        return json_response(routes[str(request.url)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await lorcast.fetch_lorcast(client, descriptor())
    assert calls == list(routes)
    assert result.records == lorcast.normalize_lorcast(bundle) and result.record_count == 2
    assert result.source_url == lorcast.LORCAST_SETS_URL
    assert result.source_revision == "sha256:" + result.source_sha256 and len(result.source_sha256) == 64
    assert not hasattr(result, "payload") and not hasattr(result, "raw")
    assert no_rate_wait.await_count == 2
    assert all(call.args == (0.25,) for call in no_rate_wait.await_args_list)


@pytest.mark.asyncio
async def test_fetch_digest_deterministic_and_sensitive_to_exact_source_bytes(no_rate_wait):
    bundle = fixture_bundle()

    async def fetch():
        routes = route_payloads(bundle)
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: json_response(routes[str(request.url)]))) as client:
            return await lorcast.fetch_lorcast(client, descriptor())

    first, second = await fetch(), await fetch()
    assert first == second
    first_card(bundle)["text"] = "different ignored rule text"
    third = await fetch()
    assert third.records == first.records and third.source_sha256 != first.source_sha256


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 403, 429, 500])
async def test_failure_after_partial_read_returns_no_snapshot_and_does_not_retry(no_rate_wait, status):
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return json_response({"results": fixture_bundle()["sets"]})
        return httpx.Response(status, text="private provider error", headers={
            "location": "http://127.0.0.1/private", "retry-after": "1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(SourceError, match=f"HTTP {status}") as error:
            await lorcast.fetch_lorcast(client, descriptor())
    assert len(calls) == 2 and "private provider error" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", [
    {"headers": {"Authorization": "private"}}, {"headers": {"X-Api-Key": "private"}},
    {"cookies": {"session": "private"}}, {"auth": ("private", "private")},
    {"params": {"api_key": "private"}},
])
async def test_authenticated_client_is_rejected_before_network(configuration):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **configuration) as client:
        with pytest.raises(SourceError, match="credential-free"):
            await lorcast.fetch_lorcast(client, descriptor())
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_provider_cookie_is_not_carried_to_later_requests(no_rate_wait):
    calls = []

    async def handler(request):
        calls.append(request)
        return json_response({"results": fixture_bundle()["sets"]},
                             **{"set-cookie": "provider_session=private; Path=/"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="credential-free"):
            await lorcast.fetch_lorcast(client, descriptor())
    assert len(calls) == 1 and "cookie" not in calls[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("change,error", [
    ({"provider": "other"}, SourceError),
    ({"system_code": "YUGIOH"}, SourceError),
    ({"download_url": "https://private.invalid"}, SourceError),
    ({"source_url": "https://private.invalid"}, SourceError),
    ({"permission_status": "REVIEW_REQUIRED"}, SourcePermissionError),
    ({"max_bytes": True}, SourceError),
    ({"max_bytes": 0}, SourceError),
])
async def test_descriptor_cannot_bypass_source_target_or_review(change, error):
    handler = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error):
            await lorcast.fetch_lorcast(client, replace(descriptor(), **change))
    handler.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pagination", "invalid_id", "request_bound", "card_schema"])
async def test_new_schema_or_untrusted_locator_stops_before_following_it(no_rate_wait, monkeypatch, mode):
    bundle = fixture_bundle()
    index = {"results": bundle["sets"]}
    if mode == "pagination":
        index["next_page"] = "https://private.invalid"
    elif mode == "invalid_id":
        bundle["sets"][0]["id"] = "https://private.invalid"
    elif mode == "request_bound":
        monkeypatch.setattr(lorcast, "MAX_REQUESTS", 2)
    calls = []

    async def handler(request):
        calls.append(request)
        return json_response(index if len(calls) == 1 else {"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError):
            await lorcast.fetch_lorcast(client, descriptor())
    assert len(calls) == (2 if mode == "card_schema" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["response", "total", "chunked", "encoding"])
async def test_response_and_total_byte_caps_fail_closed(no_rate_wait, monkeypatch, mode):
    bundle = fixture_bundle()
    routes = route_payloads(bundle)
    source = descriptor()
    if mode in {"response", "chunked"}:
        monkeypatch.setattr(lorcast, "MAX_RESPONSE_BYTES", 100)
    elif mode == "total":
        source = replace(source, max_bytes=sum(len(json.dumps(p).encode()) for p in routes.values()) - 1)
    calls = []

    async def handler(request):
        calls.append(request)
        response = json_response(routes[str(request.url)])
        if len(calls) > 1 and mode == "chunked":
            response.headers.pop("content-length", None)
        if len(calls) > 1 and mode == "encoding":
            response.headers["content-encoding"] = "gzip"
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="byte bound|Encoded response"):
            await lorcast.fetch_lorcast(client, source)
    assert len(calls) == (3 if mode == "total" else 2)


@pytest.mark.asyncio
async def test_total_elapsed_bound_stops_hanging_source(monkeypatch):
    monkeypatch.setattr(lorcast, "TOTAL_TIMEOUT_SECONDS", 0.01)
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.Future()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="total download time bound"):
            await lorcast.fetch_lorcast(client, descriptor())
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_transport_failure_has_no_retry(no_rate_wait):
    calls = []

    async def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private provider detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="transport failed") as error:
            await lorcast.fetch_lorcast(client, descriptor())
    assert len(calls) == 1 and "private provider detail" not in str(error.value)
