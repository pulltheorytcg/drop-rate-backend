from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import gzip
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app import tcgcsv_market as feed
from app.catalogue_browser import price_columns

NOW = datetime.now(timezone.utc)
GROUP = dict(groupId=24335, categoryId=80, name="Manga Booster 01", abbreviation="SB01")
REF = dict(provider="Bandai Official", system_code=feed.FUSION, language="English",
    provider_id="583201:SB01-045", name="Bulma", set_id="583201", card_number="SB01-045",
    rarity=None, set_name="MANGA BOOSTER 01 [SB01]", existing_catalogue_value=0,
    has_detail_value=False)
PRODUCT = dict(productId=634528, categoryId=80, groupId=24335, name="Bulma - SB01-045",
    url="https://www.tcgplayer.com/product/634528/dragon-ball-super-fusion-world-manga-booster-01-bulma-sb01-045",
    presaleInfo=dict(isPresale=False, releasedOn="2025-06-27T00:00:00"),
    extendedData=[dict(name="Number", value="SB01-045")])
PRICES = [dict(productId=634528, subTypeName="Holofoil", marketPrice=5.87)]
FX = SimpleNamespace(rate=Decimal("0.75"), source="ECB_TEST", effective_at=NOW, retrieved_at=NOW)


def body(rows, *, prices=False):
    return dict(success=True, errors=[], results=rows, **({} if prices else dict(totalItems=len(rows))))


def test_actual_published_sb01_identity_and_finish_are_preserved():
    assert feed.release_targets([REF], [GROUP], 80) == [(GROUP, [REF])]
    assert feed.matched_printings([REF], [PRODUCT], GROUP, NOW) == [(REF, PRODUCT)]
    quote = feed.guide_quote(REF, PRODUCT, PRICES, NOW, FX)
    assert quote["price_gbp_minor"] == 440
    assert quote["original_minor"] == 587 and quote["original_currency"] == "USD"
    assert quote["finish"] == "Holofoil"
    assert quote["physical_valuation_eligible"] is False
    assert quote["sold_comparable"] is False
    assert quote["source"] in price_columns("e")
    assert "TCGplayer US guide" in price_columns("e")


@pytest.mark.parametrize("change", ["unpriced_variant", "duplicate_reference", "wrong_number", "presale", "future", "wrong_name", "wrong_url"])
def test_missing_price_never_resolves_an_identity_collision(change):
    refs, products = [deepcopy(REF)], [deepcopy(PRODUCT)]
    if change == "unpriced_variant":
        products.append(dict(PRODUCT, productId=634529, name="Bulma - SB01-045 (Alternate Art)"))
    if change == "duplicate_reference":
        refs.append(dict(REF))
    if change == "wrong_number":
        products[0]["extendedData"][0]["value"] = "SB01-046"
    if change == "presale":
        products[0]["presaleInfo"]["isPresale"] = True
    if change == "future":
        products[0]["presaleInfo"]["releasedOn"] = (NOW+timedelta(days=10)).isoformat()
    if change == "wrong_name":
        products[0]["name"] = "Vegeta - SB01-045"
    if change == "wrong_url":
        products[0]["url"] = "https://www.tcgplayer.com/product/99999"
    assert not feed.matched_printings(refs, products, GROUP, NOW)


def test_wrong_game_release_and_incomplete_exports_fail_closed():
    assert not feed.release_targets([REF], [dict(GROUP, abbreviation="FB01")], 80)
    assert not feed.release_targets([REF], [GROUP, dict(GROUP, groupId=999)], 80)
    assert not feed.release_targets([dict(REF, language="Japanese")], [GROUP], 80)
    with pytest.raises(feed.SourceError, match="PRODUCT_IDENTITY_INVALID"):
        feed.matched_printings([REF], [dict(PRODUCT, categoryId=27)], GROUP, NOW)
    with pytest.raises(feed.SourceError, match="INCOMPLETE_COLLECTION"):
        feed.collection(dict(body([PRODUCT]), totalItems=2))
    broken = dict(PRODUCT, productId=634529,
                  extendedData=[dict(name="Number", value="SB01-045 Alt")])
    assert not feed.matched_printings([REF], [PRODUCT, broken], GROUP, NOW)
    broken["extendedData"] = [dict(name="Number", value="SB01-045")]*2
    with pytest.raises(feed.SourceError, match="PRODUCT_NUMBER_INVALID"):
        feed.matched_printings([REF], [PRODUCT, broken], GROUP, NOW)
    for stamp in ((NOW-timedelta(days=4)).isoformat(), (NOW+timedelta(days=1)).isoformat(), "2026-10-26"):
        with pytest.raises(feed.SourceError):
            feed.build_timestamp(stamp, NOW)


def test_price_validation_and_existing_other_provider_preservation():
    assert feed.guide_quote(REF, PRODUCT, PRICES+PRICES, NOW, FX) is None
    assert feed.guide_quote(REF, PRODUCT, [dict(PRICES[0], subTypeName="Unknown")], NOW, FX) is None
    assert feed.guide_quote(REF, PRODUCT, [dict(PRICES[0], marketPrice=None)], NOW, FX) is None
    assert not feed.needs_value(dict(REF, existing_catalogue_value=500, existing_source="OTHER"), NOW)
    assert not feed.needs_value(dict(REF, has_detail_value=True), NOW)
    assert feed.needs_value(dict(REF, existing_catalogue_value=500, existing_source=feed.SOURCE,
                               existing_pricing_updated_at=NOW-timedelta(days=2)), NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "snapshot", "changed_build", "rate_limit"])
async def test_real_worker_requires_verified_snapshot_before_any_price_write(monkeypatch, failure):
    events, final, calls = [], [], []
    stamp = (NOW-timedelta(hours=1)).isoformat()

    def handler(request):
        calls.append(request.url.path)
        assert request.headers["User-Agent"].startswith("DropRate/")
        if request.url.path == "/last-updated.txt":
            changed = failure == "changed_build" and calls.count("/last-updated.txt") > 1
            return httpx.Response(200, text=NOW.isoformat() if changed else stamp)
        if failure == "rate_limit":
            return httpx.Response(429)
        if request.url.path == "/tcgplayer/27/groups":
            return httpx.Response(200, json=body([]))
        if request.url.path == "/tcgplayer/80/groups":
            return httpx.Response(200, json=body([GROUP]))
        if request.url.path.endswith("/products"):
            return httpx.Response(200, json=body([PRODUCT]))
        if request.url.path.endswith("/prices"):
            return httpx.Response(200, json=body(PRICES, prices=True))
        raise AssertionError(request.url)

    class Connection:
        async def fetchval(self, *args):
            events.append("running_receipt")
            return uuid4()
        async def fetch(self, *args):
            return [REF]
        async def executemany(self, sql, rows):
            events.append("write")
            assert "reference_catalogue_prices" in sql
            assert len(rows) == 1 and rows[0][5] == 440
        async def execute(self, sql, *args):
            final.append((args[1], json.loads(args[-1])))

    @asynccontextmanager
    async def connection(*args):
        yield Connection()
    async def noop(*args):
        pass
    class FXProvider:
        async def quote(self, **kwargs):
            assert kwargs["base_currency"] == "USD"
            return FX
    class Storage:
        def put_verified_file(self, path, **kwargs):
            snapshot = json.loads(gzip.decompress(path.read_bytes()))
            assert len(snapshot["quotes"]) == 1
            assert "Description" not in json.dumps(snapshot)
            events.append("snapshot")
            return dict(verified=failure != "snapshot", sha256="a"*64, key="test", size_bytes=100)
    monkeypatch.setattr(feed, "user_connection", connection)
    monkeypatch.setattr(feed, "require_platform_admin", noop)
    monkeypatch.setattr(feed.asyncio, "sleep", noop)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await feed.refresh_exports(None, uuid4(), http_client=http, storage=Storage(), fx=FXProvider())
    assert result["writes_attempted"] == (0 if failure else 1)
    assert final[-1][0] == ("INCOMPLETE" if failure else "COMPLETE")
    assert events[0] == "running_receipt"
    if failure:
        assert "write" not in events
    else:
        assert events.index("snapshot") < events.index("write")


@pytest.mark.asyncio
async def test_restart_with_recent_receipt_spends_no_free_provider_requests():
    prior = dict(started_at=NOW-timedelta(hours=23), status="INCOMPLETE", report={})
    assert await feed.refresh_exports(None, uuid4(), previous=prior) is None
