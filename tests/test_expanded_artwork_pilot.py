"""Reference-only, no provider calls or R2 writes. Never approve candidate artwork."""
from copy import deepcopy

import pytest

from app import expanded_artwork_pilot as pilot
from app import r2_first_catalogue as catalogue
from app.r2_first_sources import normalize_ygoprodeck
from app.r2_first_lorcast import normalize_lorcast


def ygo():
    return {"data": [{"id": 12345678, "name": "Fixture Dragon", "card_sets": [
        {"set_code": "ABC-EN001", "set_name": "Fixture Set", "set_rarity": "Rare", "set_rarity_code": "R"},
        {"set_code": "ABC-EN001", "set_name": "Fixture Set", "set_rarity": "Ultra Rare", "set_rarity_code": "UR"},
    ], "card_images": [{"id": 12345678,
        "image_url": "https://images.ygoprodeck.com/images/cards/12345678.jpg"}],
        "card_prices": [{"ebay_price": "999"}], "owner_id": "secret"}]}


def ygo_ref(payload):
    row = normalize_ygoprodeck(payload)[0]
    return {**row, "key": catalogue.stable_key(row["provider"], row["system_code"],
                                                row["language"], row["provider_id"])}


def lorcana():
    source_set = {"id": "set_" + "a" * 32, "code": "1", "name": "Fixture Set"}
    card_id = "crd_" + "b" * 32
    card = {"id": card_id, "name": "Fixture Mouse", "version": "Explorer",
            "lang": "en", "collector_number": "207", "rarity": "Enchanted",
            "set": dict(source_set), "image_uris": {"digital": {"normal":
                f"https://cards.lorcast.io/card/digital/normal/{card_id}.avif?1709690747"}},
            "prices": {"usd_foil": "9999"}, "owner_id": "secret"}
    return {"sets": [source_set], "cards_by_set": {source_set["id"]: [card]}}


def lor_ref(bundle):
    row = normalize_lorcast(bundle)[0]
    return {**row, "key": catalogue.stable_key(row["provider"], row["system_code"],
                                                row["language"], row["provider_id"])}


def test_ygo_exact_single_source_image_remains_unapproved():
    source = ygo()
    reference = ygo_ref(source)
    before = deepcopy(source)
    result = pilot.preview_yugioh(source, [reference])
    assert source == before
    assert result[0]["status"] == "CARD_LEVEL_ART_PENDING_PRINT_AND_RIGHTS_REVIEW"
    assert result[0]["candidate_image_url"].endswith("/12345678.jpg")
    assert result[0]["reference_key"] == reference["key"]
    assert result[0]["rights_status"] == "PENDING_PUBLISHER_PERMISSION"
    assert not result[0]["can_mirror"] and not result[0]["can_publish"]
    assert not result[0]["image_byte_verified"] and not result[0]["printing_image_verified"]
    assert "999" not in str(result) and "secret" not in str(result)


def test_ygo_alternate_art_never_assigned_to_specific_set_or_rarity():
    source = ygo()
    source["data"][0]["card_images"].append({
        "id": 98765432, "image_url": "https://images.ygoprodeck.com/images/cards/98765432.jpg"})
    references = normalize_ygoprodeck(source)
    result = pilot.preview_yugioh(source, references)
    assert len(result) == 2
    assert all(row["status"] == "ALTERNATE_ART_SET_MAPPING_UNKNOWN" for row in result)
    assert all(row["candidate_image_url"] is None for row in result)


@pytest.mark.parametrize("bad", [
    "http://images.ygoprodeck.com/images/cards/12345678.jpg",
    "https://images.ygoprodeck.com.evil.test/images/cards/12345678.jpg",
    "https://images.ygoprodeck.com/images/cards/12345678.jpg?redirect=1",
    "https://images.ygoprodeck.com/images/cards/999.jpg",
])
def test_ygo_rejects_untrusted_or_wrong_card_images(bad):
    source = ygo()
    source["data"][0]["card_images"][0]["image_url"] = bad
    assert pilot.preview_yugioh(source, [ygo_ref(source)])[0]["status"] == "UNTRUSTED_IMAGE_LOCATOR"


def test_ygo_source_row_drift_rejects_reference_without_overwrite():
    source = ygo()
    ref = ygo_ref(source)
    ref["set_name"] = "Wrong Print"
    result = pilot.preview_yugioh(source, [ref])
    assert result[0]["status"] == "SOURCE_IDENTITY_MISMATCH"
    assert result[0]["candidate_image_url"] is None


def test_lorcana_exact_print_preview_does_not_claim_image_rights():
    source = lorcana()
    ref = lor_ref(source)
    before = deepcopy(source)
    result = pilot.preview_lorcana(source, [ref])
    assert source == before
    assert result[0]["status"] == "DIGITAL_ART_PENDING_RIGHTS_AND_PRINT_REVIEW"
    assert "crd_" in result[0]["candidate_image_url"]
    assert result[0]["rights_status"] == "PENDING_PUBLISHER_PERMISSION"
    assert not result[0]["can_publish"] and not result[0]["can_mirror"]
    assert "9999" not in str(result) and "secret" not in str(result)


def test_lorcana_wrong_print_image_is_not_accepted():
    source = lorcana()
    image = source["cards_by_set"][source["sets"][0]["id"]][0]["image_uris"]["digital"]
    image["normal"] = image["normal"].replace("crd_" + "b"*32, "crd_" + "c"*32)
    result = pilot.preview_lorcana(source, [lor_ref(source)])
    assert result[0]["status"] == "NO_VERIFIED_PRINTING_IMAGE_LOCATOR"
    assert result[0]["candidate_image_url"] is None


def test_lorcana_changed_variant_never_crosslinks():
    source = lorcana()
    ref = lor_ref(source)
    ref["card_number"] = "208"
    assert pilot.preview_lorcana(source, [ref])[0]["status"] == "SOURCE_IDENTITY_MISMATCH"


def test_invalid_reference_key_scope_and_bounds_fail_closed():
    source = ygo()
    ref = ygo_ref(source)
    for bad in [{**ref, "key": "x:" + "0" * 64},
                {**ref, "language": "Japanese"},
                {**ref, "system_code": "MAGIC_THE_GATHERING"}]:
        with pytest.raises(pilot.ArtworkPreviewError):
            pilot.preview_yugioh(source, [bad])
    with pytest.raises(pilot.ArtworkPreviewError):
        pilot.preview_yugioh(source, [ref] * 26)
    with pytest.raises(pilot.ArtworkPreviewError):
        pilot.preview_yugioh(source, [ref, ref])
