"""Only individually checked TCGdex images may use low.webp when high is absent."""
from pathlib import Path

import pytest

from app.reference_feeds import ReferenceFeeds, TCGDEX_REVIEWED_LOW_WEBP, tcgdex_reviewed_image


@pytest.mark.parametrize("provider_id", sorted(TCGDEX_REVIEWED_LOW_WEBP))
def test_exact_reviewed_printing_uses_verified_low_variant(provider_id):
    set_id, name, local, printed, path, sha256 = TCGDEX_REVIEWED_LOW_WEBP[provider_id]
    base = "https://assets.tcgdex.net/" + path
    card = {"id": provider_id, "name": name, "localId": local, "image": base}
    url, proof = tcgdex_reviewed_image("en", set_id, card, printed)
    assert url == base + "/low.webp"
    assert proof == {
        "verification": "TCGDEX_REVIEWED_LOW_WEBP_V1",
        "reviewed_at": "2026-11-01",
        "review_method": "EXACT_PRINTED_NAME_NUMBER_AND_RASTER",
        "source_url": "https://api.tcgdex.net/v2/en/cards/" + provider_id,
        "image_url": url,
        "original_high_url": base + "/high.webp",
        "content_sha256": sha256,
        "width": 245,
        "height": 337,
        "scope": "REFERENCE_ONLY_NOT_APPROVED_MEDIA",
    }


@pytest.mark.parametrize("change", ["lang", "set", "name", "local", "number", "base", "id"])
def test_altered_identity_must_not_receive_reviewed_artwork(change):
    card = {"id": "sv03.5-163", "name": "Leftovers", "localId": "163",
            "image": "https://assets.tcgdex.net/en/sv/sv03.5/163"}
    lang, set_id, printed = "en", "sv03.5", "163/165"
    if change == "lang": lang = "ja"
    if change == "set": set_id = "sv03"
    if change == "name": card["name"] = "Wrong name"
    if change == "local": card["localId"] = "164"
    if change == "number": printed = "163/999"
    if change == "base": card["image"] = "https://assets.tcgdex.net/en/sv/sv03.5/164"
    if change == "id": card["id"] = "sv03.5-164"
    url, proof = tcgdex_reviewed_image(lang, set_id, card, printed)
    assert url == card["image"] + "/high.webp"
    assert proof is None


def test_ordinary_and_missing_source_images_are_untouched():
    assert tcgdex_reviewed_image("en", "sv03.5",
        {"id": "sv03.5-164", "name": "Other", "image": "https://assets.tcgdex.net/en/sv/sv03.5/164"},
        "164/165") == ("https://assets.tcgdex.net/en/sv/sv03.5/164/high.webp", None)
    assert tcgdex_reviewed_image("en", "sv03.5", {"id": "sv03.5-164", "image": None}, "164/165") == (None, None)


@pytest.mark.asyncio
async def test_feed_writes_provenance_only_for_exact_reviewed_card():
    feed = ReferenceFeeds()
    async def get(url, **params):
        if url.endswith("/sets") and "/ja/" in url:
            return []
        if url.endswith("/sets"):
            return [{"id": "sv03.5"}]
        if url.endswith("/sets/sv03.5"):
            return {"name": "151", "releaseDate": "2023-09-22",
                    "cardCount": {"total": 207, "official": 165},
                    "cards": [
                        {"id": "sv03.5-163", "localId": "163", "name": "Leftovers",
                         "image": "https://assets.tcgdex.net/en/sv/sv03.5/163"},
                        {"id": "sv03.5-164", "localId": "164", "name": "Other",
                         "image": "https://assets.tcgdex.net/en/sv/sv03.5/164"},
                    ]}
        raise AssertionError(url)
    feed.get = get
    try:
        records = [item async for item in feed.tcgdex()]
    finally:
        await feed.close()
    assert len(records) == 1
    _, cards = records[0]
    assert cards[0]["image_url"].endswith("/163/low.webp")
    assert cards[0]["evidence"]["image_reference"]["verification"] == "TCGDEX_REVIEWED_LOW_WEBP_V1"
    assert cards[1]["image_url"].endswith("/164/high.webp")
    assert "image_reference" not in cards[1]["evidence"]


def test_data_migration_is_exact_printing_guarded_and_keeps_owner_state_out():
    sql = (Path(__file__).resolve().parents[1] / "database" / "migrations" /
           "20261101151000_tcgdex_reviewed_low_artwork.sql").read_text()
    assert "and r.language='English'" in sql
    assert "and r.image_url=v.high_url" in sql
    assert "and r.source_url='https://api.tcgdex.net/v2/en/cards/'||v.provider_id" in sql
    assert "and not (r.evidence ? 'image_reference')" in sql
    for provider_id in TCGDEX_REVIEWED_LOW_WEBP:
        assert "'" + provider_id + "'" in sql
    assert "inventory" not in sql.lower()
    assert "market_value" not in sql.lower()
