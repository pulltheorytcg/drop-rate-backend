import io
import json
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import pytest
from PIL import Image

from app import pokemon_artwork_repair as repair


def row(**changes):
    value = {"provider": "TCGdex", "system_code": "POKEMON_TCG", "language": "Japanese",
             "set_id": "SM12a", "provider_id": "SM12a-001", "name": "Exact reference",
             "card_number": "001/173", "source_url": "https://api.tcgdex.net/v2/ja/cards/SM12a-001",
             "evidence": {"provider_local_id": "001"}, "image_url": None, "candidate_total": 1}
    return {**value, **changes}


def webp(color="navy", size=(600, 825)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="WEBP")
    return out.getvalue()


def m1s_row(local="001", **changes):
    reviewed = repair.M1S_REVIEWED_CARDS.get(local, {})
    return row(set_id="M1S", provider_id=f"M1S-{local}",
               source_url=f"https://api.tcgdex.net/v2/ja/cards/M1S-{local}",
               name=reviewed.get("name", "Unreviewed"), card_number=f"{local}/63",
               evidence={"provider_local_id": local}, **changes)


def test_exact_same_language_and_local_id_path():
    item = repair.candidate(row())
    assert item["image_url"] == "https://assets.tcgdex.net/ja/SM/SM12a/001/high.webp"
    assert repair.candidate(row(evidence=json.dumps({"provider_local_id": "001"}))) == item
    assert "P-A" not in repair.SETS["English"]


def test_m1s_manifest_contains_only_individually_reviewed_identity_and_bytes():
    reviewed = repair.M1S_REVIEWED_CARDS
    assert set(reviewed) == {f"{n:03}" for n in range(1, 57)}
    assert len({r["content_sha256"] for r in reviewed.values()}) == 56
    for local, entry in reviewed.items():
        item = repair.candidate(m1s_row(local))
        assert item and item["image_url"] == f"https://assets.tcgdex.net/ja/M/M1S/{local}/high.webp"
        assert entry["printed_card_number"] == f"{local}/063"
        assert entry["width"] == 600 and entry["height"] == 825
        assert len(entry["content_sha256"]) == 64
        assert len(entry["visual_review_page_sha256"]) == 64


def test_separate_override_review_never_relaxes_the_normal_matcher():
    path = repair.M1S_REVIEW_PATH.with_name("pokemon_artwork_m1s_overrides_20261027.json")
    manifest = json.loads(path.read_text())
    entries = manifest["cards"]
    assert len(entries) == 36
    assert {entry["local_id"] for entry in entries} == {f"{n:03}" for n in range(57, 93)}
    assert len({entry["asset_local_id"] for entry in entries}) == 36
    assert len({entry["content_sha256"] for entry in entries}) == 36
    assert not ({entry["content_sha256"] for entry in entries}
                & {entry["content_sha256"] for entry in repair.M1S_REVIEWED_CARDS.values()})
    for entry in entries:
        local, asset = entry["local_id"], entry["asset_local_id"]
        assert entry["provider_id"] == f"M1S-{local}"
        assert entry["card_number"] == f"{local}/63"
        assert entry["printed_card_number"] == f"{local}/063"
        assert entry["image_url"] == f"https://assets.tcgdex.net/ja/M/M1S/{asset}/high.webp"
        assert local != asset
        assert repair.candidate({**m1s_row(local), "name": entry["name"]}) is None
    # This was absent in the original upstream report. It was independently
    # observed and reviewed on 27 October, never inferred from a numeric offset.
    assert next(entry for entry in entries if entry["local_id"] == "080")["asset_local_id"] == "073"


@pytest.mark.parametrize("local", ["000", "057", "064", "092", "001a", "1", "056-1"])
def test_m1s_unreviewed_and_misnumbered_remainder_stays_blocked(local):
    assert repair.candidate(m1s_row(local)) is None


@pytest.mark.parametrize("changes", [
    {"name": "Different printing"}, {"card_number": "001/999"},
    {"source_url": "https://api.tcgdex.net/v2/en/cards/M1S-001"},
    {"language": "English"}, {"provider_id": "M1S-002"},
])
def test_m1s_review_does_not_transfer_between_names_numbers_or_languages(changes):
    assert repair.candidate({**m1s_row(), **changes}) is None


@pytest.mark.asyncio
async def test_m1s_different_valid_raster_fails_closed():
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=webp())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified, report = await repair.probe_rows([m1s_row()], client=client)
    assert not verified
    assert report["failure_counts"] == {"REVIEWED_IMAGE_BYTES_CHANGED": 1}


@pytest.mark.asyncio
async def test_m1s_exact_reviewed_bytes_record_individual_review(monkeypatch):
    data = webp()
    original = repair.M1S_REVIEWED_CARDS["001"]
    monkeypatch.setitem(repair.M1S_REVIEWED_CARDS, "001", {
        **original, "content_sha256": repair.decoded_image(data)["content_sha256"]})
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified, report = await repair.probe_rows([m1s_row()], client=client)
    assert report["verified"] == 1
    proof = verified[0]["image_reference"]
    assert proof["verification"] == "TCGDEX_REVIEWED_IMAGE_BYTES_V1"
    assert proof["provider_issue_url"].endswith("/2395")
    assert proof["printed_card_number"] == "001/063"
    assert proof["review_manifest_sha256"] == repair.M1S_REVIEW_SHA256
    assert proof["visual_review_page_sha256"] == original["visual_review_page_sha256"]


@pytest.mark.asyncio
async def test_m1s_does_not_fallback_to_unreviewed_encoding():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        metadata, code = await repair.probe(client, repair.candidate(m1s_row()))
    assert metadata is None and code == "HTTP_404" and len(calls) == 1


@pytest.mark.asyncio
async def test_m1s_probe_rechecks_reviewed_identity_after_candidate_mutation():
    item = repair.candidate(m1s_row())
    item["name"] = "Different printing"
    async def handler(request):
        pytest.fail("Unreviewed identity reached the network")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        metadata, code = await repair.probe(client, item)
    assert metadata is None and code == "UNSAFE_IDENTITY"


@pytest.mark.parametrize("changes", [
    {"provider": "Other"}, {"system_code": "ONE_PIECE_CARD_GAME"},
    {"language": "English"}, {"language": "French"}, {"set_id": "M1S"},
    {"set_id": "unknown"}, {"provider_id": "SM12a-002"},
    {"source_url": "https://api.tcgdex.net/v2/en/cards/SM12a-001"},
    {"source_url": "https://api.tcgdex.net.evil/cards/SM12a-001"},
    {"source_url": "https://api.tcgdex.net/v2/ja/cards/SM12a-001?x=1"},
    {"image_url": "https://existing.example/image.webp"}, {"card_number": "1/173"},
    {"evidence": {}}, {"evidence": "invalid"}, {"evidence": {"provider_local_id": "../1"}},
    {"evidence": {"provider_local_id": "001?x"}}, {"name": ""},
])
def test_invalid_or_changed_identity_never_produces_candidate(changes):
    assert repair.candidate(row(**changes)) is None


def test_missing_image_whitespace_and_exact_english_promos():
    item = repair.candidate(row(language="English", set_id="svp", provider_id="svp-196",
        source_url="https://api.tcgdex.net/v2/en/cards/svp-196", card_number="196",
        evidence={"provider_local_id": "196"}, image_url=" "))
    assert item["image_url"] == "https://assets.tcgdex.net/en/sv/svp/196/high.webp"


def test_decode_actual_webp_checks_dimensions_and_hash():
    data = webp()
    result = repair.decoded_image(data)
    assert result["width"] == 600 and result["height"] == 825
    assert result["size_bytes"] == len(data)
    assert len(result["content_sha256"]) == 64


@pytest.mark.parametrize("data", [b"", b"<html>not a card</html>", b"x" * 2_000_001], ids=["empty", "html", "oversized"])
def test_invalid_bytes_are_rejected(data):
    with pytest.raises(ValueError):
        repair.decoded_image(data)


@pytest.mark.parametrize("size", [(10, 20), (600, 600), (3000, 4000), (900, 400)])
def test_invalid_dimensions_are_rejected(size):
    with pytest.raises(ValueError):
        repair.decoded_image(webp(size=size))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers,data,code", [
    (404, {}, b"", "HTTP_404"),
    (302, {"location": "https://evil.example/card.webp"}, b"", "HTTP_302"),
    (200, {"content-type": "text/html"}, b"<html>", "INVALID_CONTENT_TYPE"),
    (200, {"content-type": "image/webp", "content-length": "9000000"}, b"x", "INVALID_IMAGE_SIZE"),
    (200, {"content-type": "image/webp", "content-length": "bogus"}, b"x", "INVALID_IMAGE_SIZE"),
    (200, {"content-type": "image/webp"}, b"not an image", "INVALID_IMAGE"),
])
async def test_probe_failures_never_verify(status, headers, data, code):
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(status, headers=headers, content=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        metadata, failure = await repair.probe(client, repair.candidate(row()))
    assert metadata is None and failure == code
    assert len(calls) == (3 if status == 404 else 1)


@pytest.mark.asyncio
async def test_probe_does_not_follow_mutated_url():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=webp())
    item = repair.candidate(row())
    item["image_url"] = "http://127.0.0.1/secret"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        metadata, code = await repair.probe(client, item)
    assert metadata is None and code == "UNSAFE_URL" and not calls


@pytest.mark.asyncio
async def test_probe_checks_streamed_size_without_content_length():
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=b"x" * 2_000_001)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        metadata, code = await repair.probe(client, repair.candidate(row()))
    assert metadata is None and code == "INVALID_IMAGE_SIZE"


@pytest.mark.asyncio
async def test_probe_report_and_duplicate_placeholder_guard():
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=webp())
    second = row(provider_id="SM12a-002", source_url="https://api.tcgdex.net/v2/ja/cards/SM12a-002",
                 card_number="002/173", evidence={"provider_local_id": "002"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified, report = await repair.probe_rows([row(), second, row(language="French")], client=client)
    assert verified == []
    assert report["requested"] == 3 and report["candidates"] == 2 and report["skipped"] == 1
    assert report["failed"] == 2 and report["failure_counts"] == {"DUPLICATE_IMAGE_BYTES": 2}


@pytest.mark.asyncio
async def test_duplicate_identity_rejected_before_network():
    with pytest.raises(ValueError, match="Duplicate"):
        await repair.probe_rows([row(), row()])


@pytest.mark.asyncio
async def test_success_is_reference_only_with_source_and_actual_bytes():
    data = webp()
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified, report = await repair.probe_rows([row()], client=client)
    assert report["verified"] == 1 and report["failed"] == 0
    evidence = verified[0]["image_reference"]
    assert evidence["scope"] == "REFERENCE_ONLY_NOT_APPROVED_MEDIA"
    assert evidence["source_url"] == row()["source_url"]
    assert evidence["provider_issue_url"].endswith("/2477")
    assert evidence["size_bytes"] == len(data)
    assert evidence["content_sha256"] == repair.decoded_image(data)["content_sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_repair_is_admin_checked_and_dry_run_never_writes(monkeypatch, apply):
    writes, receipts, authorized = [], [], []
    actor = UUID(int=1)
    class Connection:
        async def fetch(self, sql, *args):
            if sql == repair.READ_SQL:
                return [row()]
            assert sql == repair.WRITE_SQL
            writes.extend(json.loads(args[0]))
            return [{"provider_id": "SM12a-001"}]
        async def fetchval(self, *args):
            receipts.append("start")
            return UUID(int=2)
        async def execute(self, sql, *args):
            receipts.append(args)
    @asynccontextmanager
    async def connection(*args):
        yield Connection()
    async def authorize(conn):
        authorized.append(True)
    async def handler(request):
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=webp())
    monkeypatch.setattr(repair, "user_connection", connection)
    monkeypatch.setattr(repair, "require_platform_admin", authorize)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        report = await repair.repair(object(), actor, apply=apply, client=client)
    assert report["verified"] == 1 and report["updated"] == int(apply)
    assert len(writes) == int(apply)
    assert len(authorized) == (4 if apply else 1)
    if apply:
        assert receipts[-1][1] == "COMPLETE"
        assert writes[0]["image_reference"]["actor_user_id"] == str(actor)
    else:
        assert not receipts


@pytest.mark.asyncio
async def test_unauthorized_repair_cannot_start_network_or_receipt(monkeypatch):
    @asynccontextmanager
    async def connection(*args):
        yield object()
    async def deny(conn):
        raise PermissionError("admin")
    monkeypatch.setattr(repair, "user_connection", connection)
    monkeypatch.setattr(repair, "require_platform_admin", deny)
    with pytest.raises(PermissionError):
        await repair.repair(object(), UUID(int=1), apply=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"apply": "true"}, {"limit": 0}, {"limit": 5001}, {"limit": True}])
async def test_invalid_options_refuse_before_database(kwargs):
    with pytest.raises(ValueError):
        await repair.repair(None, UUID(int=1), **kwargs)


@pytest.mark.asyncio
async def test_only_same_card_format_fallback_after_404():
    calls = []
    data = webp(size=(245, 337))
    async def handler(request):
        calls.append(str(request.url))
        if request.url.path.endswith("high.webp"):
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "image/webp"}, content=data)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified, report = await repair.probe_rows([row()], client=client)
    assert report["verified"] == 1 and len(calls) == 2
    expected = "https://assets.tcgdex.net/ja/SM/SM12a/001/low.webp"
    assert verified[0]["image_url"] == expected
    assert verified[0]["image_reference"]["image_url"] == expected


@pytest.mark.asyncio
async def test_png_fallback_requires_actual_png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (600, 825), "green").save(output, format="PNG")
    async def handler(request):
        if not request.url.path.endswith("high.png"):
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=output.getvalue())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified, report = await repair.probe_rows([row()], client=client)
    assert report["verified"] == 1 and verified[0]["image_url"].endswith("/001/high.png")


@pytest.mark.asyncio
async def test_time_budget_cancels_active_probe_and_reports_unexamined():
    import asyncio
    async def handler(request):
        await asyncio.sleep(10)
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified, report = await repair.probe_rows([row()], client=client, max_seconds=1)
    assert verified == [] and report["timed_out"] is True
    assert report["examined"] == 0 and report["unexamined"] == 1
    assert report["failed"] == 0


@pytest.mark.asyncio
async def test_partial_scan_persists_explicit_incomplete_receipt(monkeypatch):
    receipts = []
    class Connection:
        async def fetch(self, sql, *args):
            assert sql == repair.READ_SQL
            return [row()]
        async def fetchval(self, *args):
            return UUID(int=2)
        async def execute(self, sql, *args):
            receipts.append(args)
    @asynccontextmanager
    async def connection(*args):
        yield Connection()
    async def authorize(conn):
        pass
    async def partial(*args, **kwargs):
        return [], {"candidates": 1, "verified": 0, "failed": 0, "skipped": 0,
                    "unexamined": 1, "examined": 0, "timed_out": True, "sets": []}
    monkeypatch.setattr(repair, "user_connection", connection)
    monkeypatch.setattr(repair, "require_platform_admin", authorize)
    monkeypatch.setattr(repair, "probe_rows", partial)
    report = await repair.repair(object(), UUID(int=1), apply=True)
    assert report["status"] == "PARTIAL_TIME_BUDGET" and report["more_available"] is True
    assert report["updated"] == 0 and receipts[0][1] == "INCOMPLETE"


@pytest.mark.asyncio
@pytest.mark.parametrize("after", [
    [], ["Japanese"], ["French", "SM12a", "SM12a-001"],
    ["Japanese", "M1X", "M1X-001"], ["Japanese", "SM12a", ""],
    ["Japanese", "SM12a", "x" * 201], ["Japanese", "SM12a", chr(0)]
])
async def test_invalid_cursor_refuses_before_database(after):
    with pytest.raises(ValueError):
        await repair.repair(None, UUID(int=1), after=after)


def test_unicode_name_is_preserved_without_fuzzy_normalisation():
    name = "".join(map(chr, [0x30D4, 0x30AB, 0x30C1, 0x30E5, 0x30A6]))
    assert repair.candidate(row(name=name))["name"] == name
