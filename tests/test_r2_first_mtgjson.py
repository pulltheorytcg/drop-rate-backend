"""Bounded synthetic MTGJSON only: no live source, object-store or DB writes."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
import lzma
import threading
import time

import httpx
import pytest

from app import r2_first_mtgjson as mtg
from app.r2_first_sources import SourceDescriptor, SourceError, SourcePermissionError


def descriptor():
    return SourceDescriptor(mtg.PROVIDER, mtg.SYSTEM_CODE, mtg.DOWNLOAD_URL,
        mtg.SOURCE_REVISION, mtg.PERMISSION_REF, "METADATA_ACCESS_DOCUMENTED",
        mtg.DOWNLOAD_URL, max_bytes=mtg.MAX_COMPRESSED_BYTES)


def card(**changes):
    return {
        "uuid": "11111111-1111-5111-8111-111111111111",
        "name": "Fixture Mage", "number": "007★", "language": "English",
        "rarity": "rare", "setCode": "ABC", "finishes": ["nonfoil", "foil"],
        "availability": ["paper", "mtgo"],
        "text": "PRIVATE RULES TEXT", "flavorText": "PRIVATE FLAVOUR TEXT",
        "prices": {"usd": "12345"}, "imageUrl": "https://private.invalid/art",
        "identifiers": {"scryfallId": "shared-printing-id", "scryfallOracleId": "same-oracle-id"},
        **changes,
    }


def payload(cards=None):
    # Real MTGJSON emits cards before code/name/releaseDate; test that order.
    return {"data": {"ABC": {"cards": cards if cards is not None else [card()],
        "code": "ABC", "name": "Fixture Set", "releaseDate": "2026-01-02",
        "isOnlineOnly": False}},
        "meta": {"date": "2026-11-03", "version": "5.3.0+20261103"}}


def compressed(value=None, *, raw=None):
    return lzma.compress(raw if raw is not None else json.dumps(
        payload() if value is None else value, ensure_ascii=False).encode())


def parse(value=None, *, raw=None):
    return mtg.parse_mtgjson(io.BytesIO(compressed(value, raw=raw)))


def test_metadata_only_with_explicit_credit_and_finish_identity():
    result = parse()
    assert result.build_date == "2026-11-03"
    assert result.build_version == "5.3.0+20261103"
    assert result.source_rows == 1
    assert len(result.records) == 2
    assert {row["finish"] for row in result.records} == {"foil", "nonfoil"}
    assert len({row["provider_id"] for row in result.records}) == 2
    assert all(row["card_number"] == "007★" and row["set_id"] == "ABC"
               and row["release_date"] == "2026-01-02" for row in result.records)
    assert all(row["details"] == mtg.SOURCE_DETAILS for row in result.records)
    assert all(row["source_url"] == mtg.DOWNLOAD_URL for row in result.records)
    encoded = json.dumps(result.records)
    for excluded in ("PRIVATE", "prices", "12345", "private.invalid", "scryfallOracleId", "imageUrl"):
        assert excluded not in encoded
    assert 0 < result.normalized_raw_bytes < mtg.codec.MAX_RAW_BYTES
    assert 0 < result.estimated_output_memory_bytes < mtg.MAX_OUTPUT_MEMORY_BYTES


def test_reported_raw_bytes_match_actual_codec_parts():
    result = parse()
    prepared = mtg.codec.prepare_catalogue(result.records, provider=mtg.PROVIDER,
        system_code=mtg.SYSTEM_CODE, language="English", source_url=mtg.DOWNLOAD_URL,
        source_revision="fixture", permission_ref=mtg.PERMISSION_REF)
    assert prepared.manifest["raw_bytes"] == result.normalized_raw_bytes


def test_explicit_promo_release_date_overrides_set_cycle_date():
    result = parse(payload([card(originalReleaseDate="2026-10-29")]))
    assert all(row["release_date"] == "2026-10-29" for row in result.records)
    with pytest.raises(SourceError, match="printing release date"):
        parse(payload([card(originalReleaseDate="2026-02-30")]))


def test_explicit_signed_finish_kept_separate_without_inventing_a_grade():
    # MTGJSON PTC printings explicitly advertise nonfoil + signed. Source
    # finish evidence is an opaque identity discriminator, not grading proof.
    result = parse(payload([card(finishes=["nonfoil", "signed"])]))
    assert {row["finish"] for row in result.records} == {"nonfoil", "signed"}
    assert len({row["provider_id"] for row in result.records}) == 2
    assert all("grade" not in row for row in result.records)


def test_front_main_face_only_and_no_oracle_id_merge():
    front = card(side="a", name="Fixture Front // Fixture Back")
    back = card(uuid="22222222-2222-5222-8222-222222222222", side="b",
                name="Fixture Front // Fixture Back")
    reprint = card(uuid="33333333-3333-5333-8333-333333333333", number="8")
    result = parse(payload([front, back, reprint]))
    assert result.source_rows == 3
    assert len(result.records) == 4
    assert all(back["uuid"] not in row["provider_id"] for row in result.records)
    assert {row["card_number"] for row in result.records} == {"007★", "8"}


def test_different_set_same_name_number_remains_separate():
    value = payload()
    value["data"]["XYZ"] = deepcopy(value["data"]["ABC"])
    value["data"]["XYZ"].update(code="XYZ", name="Fixture Reprint")
    value["data"]["XYZ"]["cards"][0].update(
        setCode="XYZ", uuid="22222222-2222-5222-8222-222222222222")
    result = parse(value)
    assert len(result.records) == 4
    assert {row["set_id"] for row in result.records} == {"ABC", "XYZ"}


@pytest.mark.parametrize("changes", [
    {"language": "Japanese"}, {"availability": ["arena"]},
    {"isOnlineOnly": True}, {"side": "b"}, {"side": "c"},
])
def test_other_language_digital_and_non_front_rows_are_not_relabelled(changes):
    result = parse(payload([card(), card(uuid="22222222-2222-5222-8222-222222222222", **changes)]))
    assert len(result.records) == 2
    assert result.source_rows == 2


def test_online_only_set_is_excluded():
    value = payload()
    value["data"]["XYZ"] = deepcopy(value["data"]["ABC"])
    value["data"]["XYZ"].update(code="XYZ", isOnlineOnly=True)
    value["data"]["XYZ"]["cards"][0].update(setCode="XYZ", uuid="22222222-2222-5222-8222-222222222222")
    assert len(parse(value).records) == 2


def test_real_arena_only_empty_finishes_are_excluded_not_paper_placeholders():
    digital = card(uuid="a0f5cc4f-f297-5977-a2b1-9738f27813c4",
        name="Digital Fixture", availability=["arena"], finishes=[], isOnlineOnly=True)
    assert len(parse(payload([card(), digital])).records) == 2


def test_real_shandalar_platform_is_explicitly_not_paper():
    digital = card(uuid="d5ea3e37-a6a9-5ff1-8216-58b0ece03a4c",
        name="Aswan Jaguar", availability=["shandalar"], finishes=["nonfoil"], isOnlineOnly=True)
    assert len(parse(payload([card(), digital])).records) == 2


def test_exact_duplicate_uuid_fails_even_if_identical():
    with pytest.raises(SourceError, match="Duplicate MTGJSON printing"):
        parse(payload([card(), card()]))


@pytest.mark.parametrize("changes", [
    {"uuid": "invalid"}, {"uuid": "00000000-0000-0000-0000-000000000000"},
    {"uuid": None}, {"name": "bad\nname"}, {"number": 7}, {"number": ""},
    {"setCode": "OTHER"}, {"language": None}, {"rarity": None},
    {"availability": []}, {"availability": "paper"}, {"availability": [True]},
    {"availability": ["paper", "paper"]}, {"availability": ["unknown"]},
    {"finishes": []}, {"finishes": "foil"}, {"finishes": ["foil", "foil"]},
    {"finishes": ["malformed finish"]}, {"isOnlineOnly": "false"}, {"side": True},
])
def test_invalid_identity_evidence_fails_closed(changes):
    with pytest.raises(SourceError):
        parse(payload([card(**changes)]))


@pytest.mark.parametrize("change", [
    lambda p: p["data"]["ABC"]["cards"][0].pop("finishes"),
    lambda p: p["data"]["ABC"].update(code="XYZ"),
    lambda p: p["data"]["ABC"].update(isOnlineOnly="false"),
    lambda p: p["data"]["ABC"].update(releaseDate="2026-02-30"),
    lambda p: p["data"]["ABC"].pop("name"),
    lambda p: p["data"]["ABC"].update(cards={}),
    lambda p: p["data"]["ABC"].update(cards=[None]),
    lambda p: p.update(meta=[]),
    lambda p: p["meta"].update(date="tomorrow"),
    lambda p: p["meta"].update(version="6.0.0+20261103"),
    lambda p: p["meta"].update(version="5.3.0+20261104"),
    lambda p: p.update(data={}),
    lambda p: p.update(other=True),
])
def test_invalid_snapshot_schema_fails_closed(change):
    value = payload()
    change(value)
    with pytest.raises(SourceError):
        parse(value)


@pytest.mark.parametrize("raw", [
    b"[]", b"{}", b'{"data":{},"data":{},"meta":{}}',
    b'{"meta":{"date":"2026-11-03","date":"2026-11-03"},"data":{}}',
    b'{"data":null,"meta":{}}', b'{"data":{"ABC":null},"meta":{}}',
    b'{"data":{},"meta":{}}{}', b'{"data":{},"meta":{}} trailing',
    b'{"data":{},"meta":{"date":NaN}}', b'{"data":{},"meta":{"date":"\xff"}}',
])
def test_invalid_json_or_duplicate_keys_fails_closed(raw):
    with pytest.raises(SourceError):
        parse(raw=raw)


def test_duplicate_ignored_json_keys_also_fail():
    raw = json.dumps(payload()).encode().replace(b'"prices": {"usd": "12345"}',
                                              b'"prices":{"usd":"1","usd":"2"}')
    with pytest.raises(SourceError, match="Duplicate"):
        parse(raw=raw)


@pytest.mark.parametrize("key,value", [
    ("finishes.item", "foil"), ("availability.item", "paper"),
    ("finishes.item.extra", "foil"), ("name.extra", "Injected Name"),
])
def test_dotted_literal_card_keys_cannot_impersonate_structural_paths(key, value):
    item = card(finishes=["nonfoil"], availability=["arena"] if key.startswith("availability") else ["paper"])
    item[key] = value
    with pytest.raises(SourceError, match="dotted MTGJSON structural field"):
        parse(payload([card(uuid="22222222-2222-5222-8222-222222222222"), item]))


@pytest.mark.parametrize("location,key,value", [
    ("root", "data.ABC", {}), ("meta", "date.item", "2026-11-03"),
    ("set", "cards.item", card(uuid="22222222-2222-5222-8222-222222222222")),
    ("set", "cards.item.availability.item", "paper"),
    ("set", "cards.item.finishes.item", "foil"),
])
def test_dotted_literal_parent_keys_cannot_create_card_or_revision_paths(location, key, value):
    snapshot = payload()
    target = snapshot if location == "root" else (
        snapshot["meta"] if location == "meta" else snapshot["data"]["ABC"])
    target[key] = value
    with pytest.raises(SourceError, match="dotted MTGJSON structural field"):
        parse(snapshot)


def test_dotted_keys_in_ignored_nested_metadata_are_not_false_card_members():
    item = card(finishes=["nonfoil"], availability=["paper"])
    item["unknownProviderMetadata"] = {"finishes.item": "foil", "availability.item": "arena"}
    result = parse(payload([item]))
    assert len(result.records) == 1 and result.records[0]["finish"] == "nonfoil"


@pytest.mark.parametrize("mutation", [lambda b: b[:-12], lambda b: b + b"junk",
    lambda b: b + lzma.compress(b"{}"), lambda b: b"not xz", lambda b: b[:-3] + b"bad"])
def test_invalid_truncated_or_concatenated_xz_rejected(mutation):
    with pytest.raises(SourceError):
        mtg.parse_mtgjson(io.BytesIO(mutation(compressed())))


@pytest.mark.parametrize("constant,limit", [
    ("MAX_COMPRESSED_BYTES", 10), ("MAX_EXPANDED_BYTES", 10),
    ("MAX_SOURCE_ROWS", 0), ("MAX_SETS", 0), ("MAX_SET_SPOOL_BYTES", 10),
    ("MAX_OUTPUT_MEMORY_BYTES", 10), ("MAX_LZMA_MEMORY_BYTES", 1024),
    ("MAX_JSON_DEPTH", 2), ("MAX_JSON_EVENTS", 10),
])
def test_independent_resource_bounds_fail_closed(monkeypatch, constant, limit):
    monkeypatch.setattr(mtg, constant, limit)
    with pytest.raises(SourceError):
        parse()


@pytest.mark.parametrize("constant", ["MAX_ROWS", "MAX_RAW_BYTES"])
def test_codec_bounds_not_silently_raised_or_truncated(monkeypatch, constant):
    monkeypatch.setattr(mtg.codec, constant, 1)
    with pytest.raises(SourceError, match="no truncation"):
        parse()


def test_oversized_ignored_string_stopped_before_parser_accumulation(monkeypatch):
    monkeypatch.setattr(mtg, "MAX_TOKEN_BYTES", 100)
    value = payload()
    value["data"]["ABC"]["cards"][0]["text"] = "x" * 20_000
    with pytest.raises(SourceError, match="token exceeds memory"):
        parse(value)


def test_token_guard_escaped_quotes_and_chunk_boundaries(monkeypatch):
    monkeypatch.setattr(mtg, "MAX_TOKEN_BYTES", 128)
    guard = mtg._TokenBound()
    for chunk in (b'{"safe":"ab\\', b'"cd\\', b'\\ef"', b',"other":123}'):
        guard.check(chunk)
    assert not guard.in_string and not guard.escaped
    guard = mtg._TokenBound()
    with pytest.raises(SourceError, match="token"):
        for _ in range(20):
            guard.check(b'"' if not guard.in_string else b"a" * 50)


def test_number_token_memory_guard(monkeypatch):
    monkeypatch.setattr(mtg, "MAX_ATOM_BYTES", 10)
    with pytest.raises(SourceError, match="atom"):
        parse(raw=b'{"data":{},"meta":{"date":12345678901234567890123456789}}')


def test_timeout_and_cancellation_bound():
    with pytest.raises(SourceError, match="time bound"):
        mtg.parse_mtgjson(io.BytesIO(compressed()), deadline=time.monotonic() - 1)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(SourceError, match="cancelled"):
        mtg.parse_mtgjson(io.BytesIO(compressed()), cancelled=cancelled)


@pytest.mark.asyncio
async def test_fetch_two_fixed_requests_no_credentials_build_revision_and_checksum():
    raw = compressed()
    digest = hashlib.sha256(raw).hexdigest()
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        if str(request.url) == mtg.CHECKSUM_URL:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=digest.encode())
        assert str(request.url) == mtg.DOWNLOAD_URL
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=raw)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = await mtg.fetch_mtgjson(client, descriptor())
    assert calls == [mtg.CHECKSUM_URL, mtg.DOWNLOAD_URL]
    assert result.source_sha256 == digest and len(result.records) == 2
    assert "build=2026-11-03;version=5.3.0+20261103;sha256:" + digest in result.source_revision


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 403, 429, 500])
async def test_http_failure_never_follows_redirect_or_retries(status):
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(status, headers={"location": "https://not-followed.invalid/"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(SourceError, match=f"HTTP {status}; no retry"):
            await mtg.fetch_mtgjson(client, descriptor())
    assert calls == [mtg.CHECKSUM_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"headers": {"authorization": "secret"}}, {"cookies": {"secret": "value"}},
    {"params": {"secret": "value"}}, {"auth": ("user", "secret")},
])
async def test_credential_clients_rejected_before_any_network(options):
    async def handler(request):
        pytest.fail("No network permitted for authenticated client")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), **options) as client:
        with pytest.raises(SourceError, match="credential-free"):
            await mtg.fetch_mtgjson(client, descriptor())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"provider": "other"}, {"download_url": "https://not-followed.invalid/"},
    {"source_url": "https://not-followed.invalid/"}, {"permission_status": "REVIEW_REQUIRED"},
    {"permission_ref": "unreviewed"}, {"source_revision": "unknown"},
    {"max_bytes": mtg.MAX_COMPRESSED_BYTES + 1}, {"max_bytes": True},
])
async def test_unreviewed_or_forged_descriptor_rejected(change):
    async def handler(request):
        pytest.fail("No network permitted for invalid descriptor")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourcePermissionError):
            await mtg.fetch_mtgjson(client, replace(descriptor(), **change))


@pytest.mark.asyncio
async def test_checksum_mismatch_never_returns_partial_source():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        if str(request.url) == mtg.CHECKSUM_URL:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"0" * 64)
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=compressed())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="checksum mismatch"):
            await mtg.fetch_mtgjson(client, descriptor())
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_bulk_access_denial_after_checksum_has_no_retry_or_alternate_url():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        if str(request.url) == mtg.CHECKSUM_URL:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"0" * 64)
        return httpx.Response(403, headers={"location": "https://not-followed.invalid/"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(SourceError, match="HTTP 403; no retry"):
            await mtg.fetch_mtgjson(client, descriptor())
    assert calls == [mtg.CHECKSUM_URL, mtg.DOWNLOAD_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize("body,headers", [
    (b"invalid", {"content-type": "text/plain"}),
    (b"0" * 64, {"content-type": "text/html"}),
    (b"0" * 64, {"content-type": "text/plain", "content-encoding": "gzip"}),
    (b"0" * 64, {"content-type": "text/plain", "content-length": "999"}),
    (b"0" * 64, {"content-type": "text/plain", "content-length": "65"}),
])
async def test_checksum_response_schema_and_byte_guards(body, headers):
    async def handler(request):
        return httpx.Response(200, headers=headers, content=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError):
            await mtg.fetch_mtgjson(client, descriptor())


@pytest.mark.asyncio
async def test_response_cookie_not_forwarded_to_download():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/plain",
            "set-cookie": "secret=value; Path=/"}, content=b"0" * 64)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="credential-free"):
            await mtg.fetch_mtgjson(client, descriptor())
    assert calls == [mtg.CHECKSUM_URL]


@pytest.mark.asyncio
async def test_total_network_deadline(monkeypatch):
    monkeypatch.setattr(mtg, "TOTAL_TIMEOUT_SECONDS", 0.01)
    async def handler(request):
        await asyncio.sleep(0.05)
        pytest.fail("Timed out before any response")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="total time bound"):
            await mtg.fetch_mtgjson(client, descriptor())


@pytest.mark.asyncio
async def test_parse_is_off_thread_and_cancelled_worker_finishes_before_file_closes(monkeypatch):
    raw = compressed()
    digest = hashlib.sha256(raw).hexdigest().encode()
    main_thread = threading.get_ident()
    stopped = threading.Event()

    def worker(source, *, deadline, cancelled):
        assert threading.get_ident() != main_thread
        assert cancelled.wait(1), "worker was not cancelled"
        assert not source.closed, "temporary file closed while worker was using it"
        stopped.set()
        raise SourceError("cancelled")

    async def handler(request):
        if str(request.url) == mtg.CHECKSUM_URL:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=digest)
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=raw)

    monkeypatch.setattr(mtg, "TOTAL_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(mtg, "parse_mtgjson", worker)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="total time bound"):
            await mtg.fetch_mtgjson(client, descriptor())
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_repeated_cancellation_does_not_close_file_before_worker_stops(monkeypatch):
    raw = compressed()
    digest = hashlib.sha256(raw).hexdigest().encode()
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()
    sources = []

    def worker(source, *, deadline, cancelled):
        sources.append(source)
        started.set()
        assert release.wait(2), "test did not release worker"
        assert not source.closed, "repeated cancellation closed the active worker file"
        assert cancelled.is_set()
        stopped.set()
        raise SourceError("cancelled")

    async def handler(request):
        if str(request.url) == mtg.CHECKSUM_URL:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=digest)
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=raw)

    monkeypatch.setattr(mtg, "parse_mtgjson", worker)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        task = asyncio.create_task(mtg.fetch_mtgjson(client, descriptor()))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and not stopped.is_set()
            assert not sources[0].closed
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert stopped.is_set() and sources[0].closed


@pytest.mark.asyncio
async def test_shutdown_cancelling_all_owned_tasks_still_drains_actual_worker(monkeypatch):
    raw = compressed()
    digest = hashlib.sha256(raw).hexdigest().encode()
    started, release, stopped = threading.Event(), threading.Event(), threading.Event()
    sources = []

    def worker(source, *, deadline, cancelled):
        sources.append(source)
        started.set()
        assert release.wait(2), "test did not release worker"
        assert not source.closed, "shutdown closed the live thread's source file"
        assert cancelled.is_set()
        stopped.set()
        raise SourceError("cancelled")

    async def handler(request):
        if str(request.url) == mtg.CHECKSUM_URL:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=digest)
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=raw)

    monkeypatch.setattr(mtg, "parse_mtgjson", worker)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        baseline = set(asyncio.all_tasks())
        fetch = asyncio.create_task(mtg.fetch_mtgjson(client, descriptor()))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            # Simulate runner shutdown, without cancelling pytest's own tasks.
            # A create_task(to_thread(...)) wrapper is included here; a shielded
            # executor Future is not, preserving real worker completion state.
            for owned_task in set(asyncio.all_tasks()) - baseline:
                owned_task.cancel()
            await asyncio.sleep(0.01)
            assert not fetch.done() and not stopped.is_set()
            assert not sources[0].closed
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await fetch
    assert stopped.is_set() and sources[0].closed


@pytest.mark.asyncio
async def test_chunk_byte_guard_without_declared_length():
    class Chunked(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"0" * 80
            yield b"0" * 80

    async def handler(request):
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=Chunked())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceError, match="download byte bound"):
            await mtg.fetch_mtgjson(client, descriptor())
