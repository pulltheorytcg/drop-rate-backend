
import pytest
from app.reference_feeds import ReferenceFeeds, ReferenceFeedError, tcgdex_card_number, SV11B_NUMBER_PROOF

@pytest.mark.parametrize("official", [86, 174])
@pytest.mark.parametrize("local", ["001", "086", "087", "174"])
def test_reviewed_sv11b_denominator(official, local):
    assert tcgdex_card_number("ja", "SV11B", f"SV11B-{local}", local, official) == f"{local}/086"

@pytest.mark.parametrize("pid,local,total", [
    ("SV11W-001", "001", 174), ("SV11B-002", "001", 174),
    ("SV11B-000", "000", 174), ("SV11B-175", "175", 174),
    ("SV11B-1", "1", 174), ("SV11B-٠٠١", "٠٠١", 174),
    ("SV11B-001", "001", True), ("SV11B-001", "001", "86"),
    ("SV11B-001", "001", None), ("SV11B-001", "001", 175)])
def test_reviewed_number_rejects_changed_metadata(pid, local, total):
    with pytest.raises(ReferenceFeedError):
        tcgdex_card_number("ja", "SV11B", pid, local, total)

@pytest.mark.parametrize("lang,sid,local,total,expected", [
    ("en", "SV11B", "001", 174, "001/174"),
    ("ja", "SV11W", "001", 174, "001/174"),
    ("en", "base1", "4", 102, "4/102"), ("en", "basep", "12", None, "12")])
def test_unreviewed_releases_are_not_rewritten(lang, sid, local, total, expected):
    assert tcgdex_card_number(lang, sid, f"{sid}-{local}", local, total) == expected

@pytest.mark.asyncio
async def test_feed_preserves_total_and_unresolved_finish():
    feed = ReferenceFeeds()
    async def get(url, **params):
        if url.endswith("/en/sets"): return []
        if url.endswith("/ja/sets"): return [{"id": "SV11B"}]
        assert url.endswith("/ja/sets/SV11B")
        return {"name": "ブラックボルト", "cardCount": {"official": 174, "total": 174},
                "cards": [{"id": "SV11B-174", "localId": "174", "name": "ゼクロムex"}]}
    feed.get = get
    try:
        result = [row async for row in feed.tcgdex()]
    finally:
        await feed.close()
    record, cards = result[0]
    assert record["declared_card_count"] == 174
    assert cards[0]["card_number"] == "174/086"
    assert cards[0]["provider_id"] == "SV11B-174"
    assert cards[0]["evidence"]["collector_number_reference"] == SV11B_NUMBER_PROOF
    assert cards[0]["evidence"]["physical_finish_unresolved"] is True
    assert cards[0]["image_url"] is None
