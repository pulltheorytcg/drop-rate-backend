"""DR107: exact MTG source-print ↔ card image evidence, never automatic rights approval."""
from copy import deepcopy
import json

import pytest

from app import expanded_artwork_mtg as pilot
from app import expanded_artwork_review_cli as cli
from app import r2_first_catalogue as catalogue
from app import r2_first_mtgjson as mtg


CARD_UUID = "11111111-1111-4111-8111-111111111111"
SCRYFALL_ID = "22222222-2222-4222-8222-222222222222"


def source(*, finishes=None):
    return {"printings": [{
        "set": {"code": "TST", "name": "Test Expansion", "releaseDate": "2024-05-01"},
        "card": {
            "uuid": CARD_UUID, "name": "Fixture Mage", "number": "117",
            "language": "English", "rarity": "rare", "setCode": "TST",
            "availability": ["paper"], "finishes": finishes or ["nonfoil", "foil"],
            "identifiers": {"scryfallId": SCRYFALL_ID},
        },
        "scryfall": {
            "id": SCRYFALL_ID, "set": "tst", "name": "Fixture Mage",
            "collector_number": "117", "lang": "en", "digital": False,
            "games": ["paper"], "finishes": ["nonfoil", "foil"],
            "image_uris": {"normal":
                f"https://cards.scryfall.io/normal/front/2/2/{SCRYFALL_ID}.jpg"},
        },
    }]}


def reference(*, finish="nonfoil"):
    r = {
        "provider": "mtgjson", "system_code": "MAGIC_THE_GATHERING",
        "language": "English",
        "provider_id": f"mtgjson:{CARD_UUID}:{finish}",
        "product_type": "CARD", "name": "Fixture Mage",
        "set_id": "TST", "set_name": "Test Expansion",
        "card_number": "117", "rarity": "rare",
        "finish": finish, "release_date": "2024-05-01",
        "source_url": mtg.DOWNLOAD_URL,
    }
    r["key"] = catalogue.stable_key(
        r["provider"], r["system_code"], r["language"], r["provider_id"]
    )
    return r


def test_exact_mtg_printing_and_finish_find_one_unapproved_candidate():
    value = source()
    expected = reference()
    before = deepcopy(value)
    rows = pilot.preview_mtgjson(value, [expected, reference(finish="foil")])
    assert value == before
    assert len(rows) == 2
    assert all(row["status"] == "MTG_PRINT_ART_PENDING_FINISH_AND_RIGHTS_REVIEW" for row in rows)
    assert all(row["candidate_image_url"].endswith("/" + SCRYFALL_ID + ".jpg")
               for row in rows)
    assert all(row["rights_status"] == "PENDING_PUBLISHER_PERMISSION" for row in rows)
    assert all(not row["image_byte_verified"] and not row["printing_image_verified"]
               and not row["can_mirror"] and not row["can_publish"] for row in rows)
    assert rows[0]["reference_key"] == expected["key"]
    assert "SCRYFALL_ID" not in str(rows)
    assert "image_uris" not in str(rows)


@pytest.mark.parametrize("change", [
    {"field": "set_id", "value": "WRONG"},
    {"field": "name", "value": "Different name"},
    {"field": "card_number", "value": "118"},
    {"field": "finish", "value": "etched"},
    {"field": "language", "value": "French"},
    {"field": "source_url", "value": "https://wrong.example/data"},
])
def test_source_mismatch_never_uses_name_or_near_match(change):
    val = source()
    ref = reference()
    ref[change["field"]] = change["value"]
    if change["field"] == "language":
        with pytest.raises(pilot.ArtworkPreviewError):
            pilot.preview_mtgjson(val, [ref])
        return
    rows = pilot.preview_mtgjson(val, [ref])
    assert rows[0]["status"] == "SOURCE_IDENTITY_MISMATCH"
    assert rows[0]["candidate_image_url"] is None


@pytest.mark.parametrize("bad", [
    "http://cards.scryfall.io/normal/front/2/2/" + SCRYFALL_ID + ".jpg",
    "https://cards.scryfall.io.evil.test/normal/front/2/2/" + SCRYFALL_ID + ".jpg",
    "https://cards.scryfall.io/normal/front/2/2/" + SCRYFALL_ID + ".jpg?a=1",
    "https://cards.scryfall.io/normal/front/2/2/" + CARD_UUID + ".jpg",
    "https://cards.scryfall.io/art_crop/front/2/2/" + SCRYFALL_ID + ".jpg",
    "https://cards.scryfall.io/normal/front/1/1/" + SCRYFALL_ID + ".jpg",
])
def test_source_locator_wrong_id_or_host_is_never_used(bad):
    val = source()
    val["printings"][0]["scryfall"]["image_uris"]["normal"] = bad
    row = pilot.preview_mtgjson(val, [reference()])[0]
    assert row["status"] == "UNTRUSTED_MTG_IMAGE_LOCATOR"
    assert row["candidate_image_url"] is None


def test_missing_or_mismatched_scryfall_crosswalk_fails_closed():
    val = source()
    del val["printings"][0]["card"]["identifiers"]
    assert pilot.preview_mtgjson(val, [reference()])[0]["status"] == \
        "MISSING_SCRYFALL_PRINTING_CROSSWALK"
    val = source()
    val["printings"][0]["card"]["identifiers"]["scryfallId"] = CARD_UUID
    assert pilot.preview_mtgjson(val, [reference()])[0]["status"] == \
        "SCRYFALL_PRINTING_IDENTITY_MISMATCH"


def test_mtg_scryfall_wrong_name_set_number_and_finish_never_crosslinks():
    for field, changed in (
        ("name", "Other Mage"), ("set", "other"), ("collector_number", "118"),
        ("finishes", ["foil"]), ("lang", "fr"), ("digital", True),
    ):
        val = source()
        val["printings"][0]["scryfall"][field] = changed
        row = pilot.preview_mtgjson(val, [reference()])[0]
        assert row["candidate_image_url"] is None
        assert row["status"] in {"SCRYFALL_PRINTING_IDENTITY_MISMATCH"}


def test_multiface_no_implied_back_image_or_raw_slab_substitution():
    val = source()
    val["printings"][0]["scryfall"]["card_faces"] = [
        {"name": "Side A"}, {"name": "Side B"},
    ]
    row = pilot.preview_mtgjson(val, [reference()])[0]
    assert row["status"] == "MULTIFACE_PRINTING_REQUIRES_FRONT_BACK_REVIEW"
    assert row["candidate_image_url"] is None


def test_duplicate_source_records_and_invalid_bounds_rejected():
    val = source()
    val["printings"].append(deepcopy(val["printings"][0]))
    with pytest.raises(pilot.ArtworkPreviewError, match="Duplicate"):
        pilot.preview_mtgjson(val, [reference()])
    with pytest.raises(pilot.ArtworkPreviewError, match="1–25"):
        pilot.preview_mtgjson({"printings": []}, [reference()])
    with pytest.raises(pilot.ArtworkPreviewError, match="1–25"):
        pilot.preview_mtgjson(source(), [reference()] * 26)


def test_cli_magic_generates_a_hashed_review_not_an_image_publication(tmp_path, capsys):
    original, rows = source(), [reference()]
    a, b = tmp_path / "magic-source.json", tmp_path / "magic-references.json"
    a.write_text(json.dumps(original), encoding="utf-8")
    b.write_text(json.dumps(rows), encoding="utf-8")
    assert cli.main(["--game", "magic", "--source", str(a),
                     "--references", str(b)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == "expanded-artwork-preview-v1"
    assert report["game"] == "magic" and report["reference_count"] == 1
    assert report["all_artwork_unapproved"] is True
    assert len(report["source_sha256"]) == 64
    assert report["records"][0]["can_publish"] is False
    assert report["records"][0]["can_mirror"] is False
