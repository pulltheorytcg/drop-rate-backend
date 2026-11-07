"""DR108 live-source candidates: exact printing, HTTP safety and byte receipts."""
from copy import deepcopy
import hashlib
import io
import json

import httpx
import pytest
from PIL import Image

from app import expanded_artwork_live_pilot as live
from test_expanded_artwork_pilot import ygo, ygo_ref, lorcana, lor_ref
from test_expanded_artwork_mtg import source as magic_source, reference as magic_ref


def make_row(row):
    return {**row, "source_manifest_sha256": "f" * 64}


def client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(4),
        follow_redirects=False,
        headers=live.HEADERS,
    )


def test_real_source_contract_only_accepts_published_exact_reference_and_five_max():
    ref = make_row(ygo_ref(ygo()))
    assert live._identity(ref, "ygoprodeck", "YUGIOH") == ref["key"]
    for bad in [
        {**ref, "key": "x:" + "0" * 64},
        {**ref, "language": "Japanese"},
        {**ref, "source_manifest_sha256": None},
        {**ref, "provider": "lorcast"},
    ]:
        with pytest.raises(live.ArtworkPreviewError):
            live._identity(bad, "ygoprodeck", "YUGIOH")


@pytest.mark.asyncio
async def test_real_ygo_set_code_card_passcode_and_single_artwork_candidate():
    payload = ygo()
    # Review one original set/rarity per card while maintaining the real
    # provider SHA tuple derived by production normalization.
    raw_card = payload["data"][0]
    ref = make_row(ygo_ref(payload))
    calls = []
    def handler(req):
        calls.append(str(req.url))
        assert req.headers.get("user-agent") == live.HEADERS["User-Agent"]
        if req.url.path.endswith("/cardsetsinfo.php"):
            assert req.url.params["setcode"] == ref["card_number"]
            return httpx.Response(200, json={
                "id": raw_card["id"], "set_code": ref["card_number"],
                "set_name": ref["set_name"], "set_rarity": ref["rarity"],
            })
        if req.url.path.endswith("/cardinfo.php"):
            assert req.url.params["id"] == str(raw_card["id"])
            return httpx.Response(200, json={"data": [raw_card]})
        raise AssertionError("Unlisted source URL")
    async with client(handler) as http:
        receipt = await live.collect("YUGIOH", [ref], client=http)
    assert receipt["candidate_count"] == 1
    assert receipt["records"][0]["candidate_image_url"].endswith("/12345678.jpg")
    assert receipt["records"][0]["status"] == "CARD_LEVEL_ART_PENDING_PRINT_AND_RIGHTS_REVIEW"
    assert receipt["records"][0]["can_publish"] is False
    assert receipt["storage_writes"] == receipt["database_writes"] == 0
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_ygo_rejects_printing_source_mismatch_without_following_image():
    payload = ygo()
    ref = make_row(ygo_ref(payload))
    def handler(req):
        return httpx.Response(200, json={
            "id": 12345678, "set_code": "WRONG-001",
            "set_name": ref["set_name"], "set_rarity": ref["rarity"],
        })
    async with client(handler) as http:
        receipt = await live.collect("YUGIOH", [ref], client=http, verify_bytes=True)
    assert receipt["candidate_count"] == 0
    assert receipt["records"][0]["status"] == "YGO_SET_PRINTING_IDENTITY_MISMATCH"


@pytest.mark.asyncio
async def test_lorcana_exact_crd_set_print_and_image_url():
    source = lorcana()
    raw_card = source["cards_by_set"][source["sets"][0]["id"]][0]
    ref = make_row(lor_ref(source))
    def handler(req):
        assert req.url.path.endswith("/cards/1/207")
        return httpx.Response(200, json=raw_card)
    async with client(handler) as http:
        result = await live.collect("DISNEY_LORCANA", [ref], client=http)
    assert result["candidate_count"] == 1
    assert result["records"][0]["status"] == "DIGITAL_ART_PENDING_RIGHTS_AND_PRINT_REVIEW"
    assert "crd_" in result["records"][0]["candidate_image_url"]
    assert result["records"][0]["rights_status"] == "PENDING_PUBLISHER_PERMISSION"


@pytest.mark.asyncio
async def test_magic_exact_set_collector_finish_scryfall_candidate_is_not_crosswalk_approved():
    ref = make_row(magic_ref())
    scryfall = {**magic_source()["printings"][0]["scryfall"], "rarity": "rare"}
    def handler(req):
        assert req.url.path == "/cards/tst/117"
        return httpx.Response(200, json=scryfall)
    async with client(handler) as http:
        result = await live.collect("MAGIC_THE_GATHERING", [ref], client=http)
    assert result["candidate_count"] == 1
    assert result["records"][0]["status"] == (
        "MTG_IMAGE_CANDIDATE_PENDING_SOURCE_UUID_CROSSWALK_AND_RIGHTS"
    )
    assert not result["records"][0]["image_byte_verified"]
    assert result["can_publish"] is False and result["can_mirror"] is False


@pytest.mark.asyncio
async def test_magic_wrong_set_rarity_or_finish_rejected_without_crosslink():
    source = {**magic_source()["printings"][0]["scryfall"], "rarity": "rare"}
    for key, value in [("collector_number", "118"), ("rarity", "uncommon"),
                       ("finishes", ["foil"]), ("set", "other")]:
        card = {**source, key: value}
        def handler(req):
            return httpx.Response(200, json=card)
        async with client(handler) as http:
            result = await live.collect("MAGIC_THE_GATHERING", [make_row(magic_ref())], client=http)
        assert result["candidate_count"] == 0
        assert result["records"][0]["status"] == "MTG_SET_COLLECTOR_FINISH_MISMATCH"


@pytest.mark.asyncio
async def test_magic_multiface_requires_manual_front_back_review():
    source = magic_source()["printings"][0]["scryfall"]
    source["card_faces"] = [{"name": "Front"}, {"name": "Back"}]
    async with client(lambda req: httpx.Response(200, json=source)) as http:
        result = await live.collect("MAGIC_THE_GATHERING", [make_row(magic_ref())], client=http)
    assert result["records"][0]["status"] == "MTG_MULTIFACE_FRONT_BACK_REVIEW_REQUIRED"
    assert result["candidate_count"] == 0


@pytest.mark.asyncio
async def test_byte_probe_decodes_one_real_jpeg_and_reports_hash_not_approval():
    target = make_row(ygo_ref(ygo()))
    image = Image.new("RGB", (300, 420), (255, 200, 128))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    payload = buffer.getvalue()
    url = "https://images.ygoprodeck.com/images/cards/12345678.jpg"
    async with client(lambda req: httpx.Response(
        200, headers={"Content-Type": "image/jpeg"}, content=payload
    )) as http:
        receipt = await live._verify_bytes(http, live._decision(
            target, target["key"], "CARD_LEVEL_ART_PENDING_PRINT_AND_RIGHTS_REVIEW", url
        ))
    assert receipt["image_byte_verified"] is True
    assert receipt["image_sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["image_dimensions"] == {"width": 300, "height": 420}
    assert not receipt["can_publish"] and not receipt["can_mirror"]


@pytest.mark.asyncio
async def test_unsafe_url_or_oversized_data_never_becomes_verified_image():
    target = make_row(ygo_ref(ygo()))
    for url in [
        "https://images.ygoprodeck.com.evil.test/images/cards/12345678.jpg",
        "http://images.ygoprodeck.com/images/cards/12345678.jpg",
        "https://images.ygoprodeck.com/images/cards/12345678.jpg#frag",
    ]:
        async with client(lambda req: (_ for _ in ()).throw(AssertionError("Should not fetch"))) as http:
            receipt = await live._verify_bytes(http, live._decision(
                target, target["key"], "REVIEW", url
            ))
        assert receipt["image_byte_verified"] is False


@pytest.mark.asyncio
async def test_explicit_provider_429_fails_remaining_rows_closed():
    ref = make_row(ygo_ref(ygo()))
    async with client(lambda req: httpx.Response(429, json={"error": "rate limited"})) as http:
        result = await live.collect("YUGIOH", [ref], client=http)
    assert result["records"][0]["status"] == "PROVIDER_RATE_LIMITED"
    assert result["candidate_count"] == 0
    assert result["storage_writes"] == 0


@pytest.mark.asyncio
async def test_duplicate_reference_and_oversized_pilot_rejected_before_network():
    ref = make_row(ygo_ref(ygo()))
    with pytest.raises(live.ArtworkPreviewError, match="Duplicate"):
        await live.collect("YUGIOH", [ref, ref])
    with pytest.raises(live.ArtworkPreviewError, match="1–5"):
        await live.collect("YUGIOH", [ref] * 6)
