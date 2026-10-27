from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.book_ebay_context import BookListingContextService


PATH = Path(__file__).resolve().parents[1] / "backend/scripts/book_ebay_context_probe.py"
spec = importlib.util.spec_from_file_location("book_context_probe_for_tests", PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def args(**updates):
    values = dict(isbn=None, title=None, volume=None, language=None, binding=None, publisher=None, listing_id=None)
    return SimpleNamespace(**{**values, **updates})


@pytest.mark.asyncio
async def test_probe_skips_without_exact_flag_before_reading_settings(monkeypatch):
    monkeypatch.setattr(probe, "get_settings", lambda: (_ for _ in ()).throw(AssertionError("settings must not load")))
    result = await probe.run_probe(args())
    assert result["status"] == "SKIPPED"
    assert result["browse_calls"] == 0
    assert result["persisted"] is False


@pytest.mark.asyncio
async def test_probe_rejects_old_ui_fixture_and_conflicting_title_without_provider(monkeypatch):
    monkeypatch.setattr(probe, "service_from_settings", lambda _: (_ for _ in ()).throw(AssertionError("no provider")))
    old = args()
    old.isbn = "9781598163476"
    assert (await probe.run_probe(old))["reason"] == "PINNED_PILOT_ISBN_REQUIRED"
    wrong = args()
    wrong.isbn, wrong.title = probe.PILOT_ISBN, "Different title"
    assert (await probe.run_probe(wrong))["reason"] == "PILOT_IDENTITY_CONFLICT"


@pytest.mark.asyncio
async def test_probe_returns_sanitized_allowlisted_diagnostics_and_call_count(monkeypatch):
    class Service:
        calls_used = 4
        async def get(self, target, *, diagnostics):
            assert target.isbn == "9781427800022"
            assert target.catalogue_id == "607ab7c5-4e33-5bd0-8725-640ccb506c98"
            assert target.binding == "Paperback" and diagnostics
            return {"status": "UNAVAILABLE", "reason": "NO_EXACT_ACTIVE_LISTINGS",
                    "diagnostics": {"candidate_count": 3, "detail_count": 3,
                                    "candidates": [{"reason": "ISBN_MISSING_OR_CONFLICT"}]}}
    monkeypatch.setattr(probe, "service_from_settings", lambda _: Service())
    flag = args()
    flag.isbn = probe.PILOT_ISBN
    result = await probe.run_probe(flag, settings=object())
    assert result["browse_calls"] == 4
    assert result["status"] == "UNAVAILABLE"
    assert result["result"]["diagnostics"]["detail_count"] == 3


@pytest.mark.asyncio
async def test_naruto_probe_uses_its_own_publisher_identity_without_inferred_binding(monkeypatch):
    targets = []

    class Service:
        calls_used = 1

        async def get(self, target, *, diagnostics):
            targets.append(target)
            assert diagnostics
            return {"status": "UNAVAILABLE", "reason": "NO_EXACT_ACTIVE_LISTINGS"}

    monkeypatch.setattr(probe, "service_from_settings", lambda _: Service())
    result = await probe.run_probe(args(
        isbn="9781569319000", title="Naruto", volume="1", language="English",
        publisher="VIZ Media"), settings=object())
    assert result["status"] == "UNAVAILABLE"
    assert result["source_url"] == "https://www.viz.com/manga-books/manga/naruto-volume-1-0/product/91"
    assert result["browse_calls"] == 1
    assert len(targets) == 1
    target = targets[0]
    assert target.isbn == "9781569319000"
    assert target.catalogue_id == "9264f778-e6a2-5f59-b0d2-23e8d725f4e5"
    assert (target.title, target.volume, target.language, target.publisher) == ("Naruto", "1", "English", "VIZ Media")
    assert target.release_year == 2003
    assert target.binding is None
    assert probe.NARUTO_PILOT["attributes"]["identity_source"] == "OFFICIAL_PUBLISHER_CATALOGUE"
    assert probe.NARUTO_PILOT["attributes"]["book_format"] == "MANGA"


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [
    {"title": "+Anima"}, {"volume": "2"}, {"language": "Japanese"},
    {"publisher": "TokyoPop"}, {"binding": "Paperback"}, {"binding": "Hardcover"},
])
async def test_naruto_probe_rejects_conflicting_or_unknown_identity_before_settings(monkeypatch, identity):
    monkeypatch.setattr(probe, "get_settings", lambda: (_ for _ in ()).throw(AssertionError("settings must not load")))
    result = await probe.run_probe(args(isbn="9781569319000", **identity))
    assert result["reason"] == "PILOT_IDENTITY_CONFLICT"
    assert result["browse_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("isbn,title,publisher", [
    ("9781427800022", "Naruto", "VIZ Media"),
    ("9781569319000", "+Anima", "TokyoPop"),
    ("9781598163476", "+Anima", "TokyoPop"),
])
async def test_pinned_isbns_never_share_edition_flags_or_admit_regular_anima(monkeypatch, isbn, title, publisher):
    monkeypatch.setattr(probe, "get_settings", lambda: (_ for _ in ()).throw(AssertionError("settings must not load")))
    result = await probe.run_probe(args(isbn=isbn, title=title, publisher=publisher))
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == ("PINNED_PILOT_ISBN_REQUIRED" if isbn == "9781598163476" else "PILOT_IDENTITY_CONFLICT")
    assert result["browse_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("isbn", ["9781427800022", "9781569319000"])
async def test_each_selected_pilot_is_one_bounded_lookup_without_fallback_to_other_fixture(monkeypatch, isbn):
    searches, details = [], []

    class Client:
        async def search_items(self, **query):
            await self._before_browse_request()
            searches.append(query)
            return {"itemSummaries": [{"itemId": f"v1|1234567890{i:02d}|0"} for i in range(10)]}

        async def get_item(self, item_id):
            await self._before_browse_request()
            details.append(item_id)
            return {}

    service = BookListingContextService(Client())
    monkeypatch.setattr(probe, "service_from_settings", lambda _: service)
    result = await probe.run_probe(args(isbn=isbn), settings=object())
    assert [query["gtin"] for query in searches] == [isbn]
    assert len(details) == 3
    assert result["browse_calls"] == 4
    assert result["status"] == "UNAVAILABLE"
    assert result["result"]["isbn"] == isbn
    assert result["result"]["diagnostics"]["search_count"] == 1
    assert result["result"]["diagnostics"]["detail_count"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("isbn,listing_id", [
    ("9781569319000", "123456789012"), ("9781427800022", "298583744784"),
    ("9781569319000", "v1|298583744784|0"), ("9781569319000", "https://www.ebay.co.uk/itm/298583744784"),
    ("9781569319000", "298583744784?redirect=anything"), ("9781569319000", []),
])
async def test_pinned_listing_probe_rejects_any_other_id_or_edition_before_settings(monkeypatch, isbn, listing_id):
    monkeypatch.setattr(probe, "get_settings", lambda: (_ for _ in ()).throw(AssertionError("no settings or provider")))
    result = await probe.run_probe(args(isbn=isbn, listing_id=listing_id))
    assert result["status"] == "UNAVAILABLE" and result["reason"] == "PINNED_LISTING_ID_REQUIRED"
    assert result["browse_calls"] == 0


@pytest.mark.asyncio
async def test_pinned_listing_id_does_not_replace_the_exact_isbn_opt_in(monkeypatch):
    monkeypatch.setattr(probe, "get_settings", lambda: (_ for _ in ()).throw(AssertionError("no settings or provider")))
    result = await probe.run_probe(args(listing_id="298583744784"))
    assert result["status"] == "SKIPPED" and result["browse_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("listing_id", ["298583744784", "800761400014"])
async def test_each_pinned_naruto_listing_uses_shared_validation_with_at_most_two_calls(monkeypatch, listing_id):
    calls = []
    item_id = f"v1|{listing_id}|0"
    product = {"itemId": item_id, "title": "Naruto Volume 1 Paperback", "product": {},
               "sellerItemRevision": "12", "price": {"currency": "GBP", "value": "5.03"},
               "itemWebUrl": f"https://www.ebay.co.uk/itm/{listing_id}",
               "buyingOptions": ["FIXED_PRICE"], "condition": "Good", "itemLocation": {"country": "GB"},
               "localizedAspects": [{"name": "Language", "value": "English"},
                                    {"name": "Format", "value": "Paperback"},
                                    {"name": "Publisher", "value": "VIZ Media"},
                                    {"name": "Publication Year", "value": "2003"}],
               "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 2}]}
    compact = {key: product[key] for key in ("itemId", "sellerItemRevision", "price", "itemWebUrl", "estimatedAvailabilities")}
    compact["gtin"] = "9781569319000"

    class Client:
        async def search_items(self, **query):
            raise AssertionError("pinned probe must not search")

        async def get_item(self, requested, *, fieldgroups="PRODUCT"):
            await self._before_browse_request()
            assert requested == item_id
            calls.append((requested, fieldgroups))
            return product if fieldgroups == "PRODUCT" else compact

    service = BookListingContextService(Client())
    monkeypatch.setattr(probe, "service_from_settings", lambda _: service)
    result = await probe.run_probe(args(isbn="9781569319000", listing_id=listing_id), settings=object())
    assert result["status"] == "AVAILABLE" and result["browse_calls"] == 2
    assert result["requested_listing_id"] == listing_id
    assert calls == [(item_id, "PRODUCT"), (item_id, "COMPACT")]
    assert result["result"]["items"][0]["price_minor"] == 503
    assert result["result"]["diagnostics"]["search_count"] == 0
    assert result["result"]["diagnostics"]["compact_count"] == 1
    assert result["result"]["edition"]["binding"] is None
    assert result["physical_valuation_eligible"] is False and result["persisted"] is False
    assert not service.cache


@pytest.mark.asyncio
async def test_probe_configuration_exception_does_not_print_secrets(monkeypatch):
    monkeypatch.setattr(probe, "get_settings", lambda: (_ for _ in ()).throw(RuntimeError("Bearer secret-private-token")))
    flag = args()
    flag.isbn = probe.PILOT_ISBN
    result = await probe.run_probe(flag)
    assert result["status"] == "UNAVAILABLE"
    assert "secret-private-token" not in json.dumps(result)


def test_default_cli_run_is_a_single_json_skip_record(monkeypatch, capsys):
    monkeypatch.delenv("TCG_BOOK_EBAY_CONTEXT_PROBE_ISBN", raising=False)
    assert probe.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "SKIPPED"
