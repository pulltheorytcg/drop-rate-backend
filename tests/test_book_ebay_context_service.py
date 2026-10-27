from __future__ import annotations

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app import book_ebay_context as context
from app.ebay_official_client import EbayApiError


NOW = datetime(2026, 10, 27, 21, tzinfo=timezone.utc)
CATALOGUE_ID = "607ab7c5-4e33-5bd0-8725-640ccb506c98"
ROW = {"catalogue_id": CATALOGUE_ID, "product_type": "COMIC", "system_code": "MANGA",
       "series_title": "+Anima", "issue_number": "1", "volume_identifier": "Paperback",
       "release_year": 2006, "language": "English", "barcode_gtin": "9781427800022",
       "identity_status": "STRUCTURED", "profile_status": "STRUCTURED", "version": 1,
       "attributes": {"publisher": "TokyoPop", "book_format": "MANGA", "identity_source": "OPEN_LIBRARY_CATALOGUE"}}


def detail(number=1):
    return {"itemId": f"v1|12345678901{number}|0", "title": "+Anima Volume 1 Paperback",
            "product": {"gtins": ["9781427800022"]},
            "localizedAspects": [{"name": "Language", "value": "English"}, {"name": "Format", "value": "Paperback"}],
            "itemLocation": {"country": "GB"}, "price": {"currency": "GBP", "value": str(10 + number)},
            "buyingOptions": ["FIXED_PRICE"], "condition": "Very Good",
            "itemWebUrl": f"https://www.ebay.co.uk/itm/12345678901{number}",
            "shippingOptions": [{"shippingCost": {"currency": "GBP", "value": "8.99"}}],
            "image": {"imageUrl": "https://i.ebayimg.com/images/g/ABC123/s-l500.jpg"}}


class FakeClient:
    def __init__(self, *, error=None, details=None):
        self.calls = []
        self.error = error
        self.details = details or [detail(i) for i in range(1, 5)]
        self.started = asyncio.Event()
        self.release = None

    async def search_items(self, **kwargs):
        await self._before_browse_request()
        self.calls.append(("search", kwargs))
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error:
            raise self.error
        return {"itemSummaries": [{"itemId": d["itemId"]} for d in self.details]}

    async def get_item(self, item_id):
        await self._before_browse_request()
        self.calls.append(("detail", item_id))
        row = next(d for d in self.details if d["itemId"] == item_id)
        if isinstance(row.get("error"), Exception):
            raise row["error"]
        return copy.deepcopy(row)


def service(client=None, **kwargs):
    return context.BookListingContextService(client or FakeClient(), utcnow=lambda: NOW, **kwargs)


@pytest.mark.asyncio
async def test_one_gtin_search_and_at_most_three_details_without_a_sold_value():
    client = FakeClient()
    svc = service(client)
    result = await svc.get(context.edition_target(ROW), diagnostics=True)
    assert result["status"] == "AVAILABLE"
    assert result["item_count"] == len(result["items"]) == 3
    assert (result["asking_low_minor"], result["asking_high_minor"]) == (1100, 1300)
    assert result["items"][0]["shipping_minor"] == 899
    assert client.calls[0] == ("search", {"gtin": "9781427800022", "limit": 10, "item_location_country": "GB", "fixed_price_only": True})
    assert svc.calls_used == len(client.calls) == 4
    assert result["observation_type"] == "ACTIVE"
    assert result["physical_valuation_eligible"] is False
    assert "market_value_minor" not in result
    assert datetime.fromisoformat(result["expires_at"]) - NOW == timedelta(hours=1)
    assert result["diagnostics"]["detail_count"] == 3


@pytest.mark.asyncio
async def test_concurrent_owners_share_inflight_request_and_return_independent_objects():
    client = FakeClient()
    client.release = asyncio.Event()
    svc = service(client)
    target = context.edition_target(ROW)
    tasks = [asyncio.create_task(svc.get(target)) for _ in range(20)]
    await client.started.wait()
    assert len(client.calls) == 1
    client.release.set()
    results = await asyncio.gather(*tasks)
    assert len(client.calls) == 4
    assert not svc.inflight
    results[0]["items"].clear()
    assert len(results[1]["items"]) == 3
    assert "diagnostics" not in results[1]


@pytest.mark.asyncio
async def test_navigation_cancellation_does_not_cancel_shared_fetch():
    client = FakeClient()
    client.release = asyncio.Event()
    svc = service(client)
    target = context.edition_target(ROW)
    first = asyncio.create_task(svc.get(target))
    await client.started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(svc.get(target))
    client.release.set()
    assert (await second)["status"] == "AVAILABLE"
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_cache_is_identity_bound_bounded_and_expires_using_monotonic_time():
    clock = [100.0]
    client = FakeClient()
    svc = service(client, monotonic=lambda: clock[0], cache_size=1)
    target = context.edition_target(ROW)
    await svc.get(target)
    await svc.get(target)
    assert len(client.calls) == 4
    changed = context.edition_target({**ROW, "version": 2})
    assert changed.digest != target.digest
    await svc.get(changed)
    assert len(client.calls) == 8
    assert len(svc.cache) == 1
    clock[0] += 3601
    await svc.get(changed)
    assert len(client.calls) == 12


@pytest.mark.asyncio
async def test_daily_budget_counts_attempts_and_never_exposes_partial_success():
    client = FakeClient()
    svc = service(client, daily_call_limit=2)
    result = await svc.get(context.edition_target(ROW))
    assert len(client.calls) == svc.calls_used == 2
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "DAILY_CALL_LIMIT"
    assert result["items"] == []
    assert result["asking_low_minor"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [(401, "PROVIDER_ACCESS_REQUIRED"), (403, "PROVIDER_ACCESS_REQUIRED"), (429, "PROVIDER_RATE_LIMIT")])
async def test_provider_refusal_stops_all_identities_without_retry(status, reason):
    client = FakeClient(error=EbayApiError("never print secret", status_code=status, retryable=True, retry_after_seconds=1200))
    svc = service(client)
    result = await svc.get(context.edition_target(ROW), diagnostics=True)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == reason
    assert result["diagnostics"]["provider_status_code"] == status
    changed = context.edition_target({**ROW, "version": 2})
    assert (await svc.get(changed))["reason"] == reason
    assert len(client.calls) == svc.calls_used == 1
    assert "never print secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_429_backoff_is_monotonic_and_honours_retry_after():
    clock = [500.0]
    client = FakeClient(error=EbayApiError("rate limit", status_code=429, retry_after_seconds=1200))
    svc = service(client, monotonic=lambda: clock[0])
    await svc.get(context.edition_target(ROW))
    assert svc.blocked_until == 1700.0
    client.error = None
    clock[0] = 1699.99
    assert (await svc.get(context.edition_target({**ROW, "version": 2})))["reason"] == "PROVIDER_RATE_LIMIT"
    assert len(client.calls) == 1
    clock[0] = 1700.01
    assert (await svc.get(context.edition_target({**ROW, "version": 3})))["status"] == "AVAILABLE"


@pytest.mark.asyncio
async def test_actual_provider_timeout_still_stops_following_requests():
    client = FakeClient(error=TimeoutError("private provider timeout context"))
    svc = service(client, monotonic=lambda: 100.0)
    result = await svc.get(context.edition_target(ROW))
    assert result["reason"] == "PROVIDER_UNAVAILABLE"
    assert svc.blocked_until == 400.0
    assert (await svc.get(context.edition_target({**ROW, "version": 2})))["reason"] == "PROVIDER_UNAVAILABLE"
    assert len(client.calls) == svc.calls_used == 1
    assert "private provider" not in json.dumps(result)


@pytest.mark.asyncio
async def test_daily_budget_resets_only_on_a_new_utc_day():
    wall = [NOW]
    svc = context.BookListingContextService(FakeClient(), daily_call_limit=1, utcnow=lambda: wall[0])
    await svc.reserve_call()
    with pytest.raises(context.ContextUnavailable):
        await svc.reserve_call()
    wall[0] += timedelta(days=1)
    await svc.reserve_call()
    assert svc.calls_used == 1


@pytest.mark.asyncio
async def test_provider_detail_failure_after_a_match_discards_partial_range():
    rows = [detail(1), {**detail(2), "error": EbayApiError("private body", status_code=503)}]
    svc = service(FakeClient(details=rows))
    result = await svc.get(context.edition_target(ROW))
    assert result["status"] == "UNAVAILABLE"
    assert result["items"] == []
    assert result["asking_high_minor"] is None


@pytest.mark.asyncio
async def test_earliest_listing_end_caps_response_expiry_and_monotonic_cache():
    wall, mono = [NOW], [100.0]
    ends = (NOW + timedelta(seconds=25)).isoformat()
    client = FakeClient(details=[{**detail(), "itemEndDate": ends}])
    svc = context.BookListingContextService(client, utcnow=lambda: wall[0], monotonic=lambda: mono[0])
    target = context.edition_target(ROW)
    result = await svc.get(target)
    assert result["expires_at"] == ends
    assert svc.cache[target.digest][0] == 125.0
    wall[0] += timedelta(seconds=26)
    mono[0] += 26
    refreshed = await svc.get(target)
    assert refreshed["status"] == "UNAVAILABLE"
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_item_that_ends_during_other_detail_reads_is_not_returned():
    wall = [NOW]
    class AdvancingClient(FakeClient):
        async def get_item(self, item_id):
            result = await super().get_item(item_id)
            if item_id == self.details[-1]["itemId"]:
                wall[0] += timedelta(seconds=30)
            return result
    rows = [{**detail(1), "itemEndDate": (NOW + timedelta(seconds=20)).isoformat()}, detail(2)]
    svc = context.BookListingContextService(AdvancingClient(details=rows), utcnow=lambda: wall[0])
    result = await svc.get(context.edition_target(ROW))
    assert result["item_count"] == 1
    assert result["items"][0]["item_id"] == detail(2)["itemId"]


@pytest.mark.asyncio
async def test_mixed_auction_and_buy_it_now_does_not_become_an_asking_reference():
    client = FakeClient(details=[{**detail(), "buyingOptions": ["AUCTION", "FIXED_PRICE"],
                                 "currentBidPrice": {"value": "1", "currency": "GBP"}}])
    result = await service(client).get(context.edition_target(ROW))
    assert result["status"] == "UNAVAILABLE"
    assert result["items"] == []


@pytest.mark.asyncio
async def test_global_inflight_bound_rejects_extra_identities_without_more_calls():
    client = FakeClient()
    client.release = asyncio.Event()
    svc = service(client, max_inflight=1)
    first = asyncio.create_task(svc.get(context.edition_target(ROW)))
    await client.started.wait()
    second = await svc.get(context.edition_target({**ROW, "version": 2}))
    assert second["reason"] == "BUSY"
    assert datetime.fromisoformat(second["expires_at"]) - NOW == timedelta(seconds=5)
    assert len(client.calls) == 1
    client.release.set()
    await first


@pytest.mark.asyncio
async def test_three_targets_admission_timeout_does_not_back_off_healthy_provider_requests():
    """Two slow requests retain their slots; a queued third can retry promptly."""
    both_started, release = asyncio.Event(), asyncio.Event()

    class GatedClient(FakeClient):
        async def search_items(self, **kwargs):
            await self._before_browse_request()
            self.calls.append(("search", kwargs))
            if sum(call[0] == "search" for call in self.calls) == 2:
                both_started.set()
            await release.wait()
            return {"itemSummaries": [{"itemId": d["itemId"]} for d in self.details
                                      if d["product"]["gtins"] == [kwargs["gtin"]]]}

    rows = [ROW, {**ROW, "catalogue_id": str(UUID(int=2)), "barcode_gtin": "9781598163476"},
            {**ROW, "catalogue_id": str(UUID(int=3)), "barcode_gtin": "9781569319000",
             "series_title": "Naruto", "release_year": 2003,
             "attributes": {**ROW["attributes"], "publisher": "VIZ Media"}}]
    targets = [context.edition_target(row) for row in rows]
    details = [{**detail(i), "title": f"{target.title} Volume 1 Paperback",
                "product": {"gtins": [target.isbn]}} for i, target in enumerate(targets, start=1)]
    client = GatedClient(details=details)
    wall, mono = [NOW], [100.0]
    svc = context.BookListingContextService(client, utcnow=lambda: wall[0], monotonic=lambda: mono[0])
    active = [asyncio.create_task(svc.get(target)) for target in targets[:2]]
    try:
        await asyncio.wait_for(both_started.wait(), timeout=1)
        busy = await asyncio.wait_for(svc.get(targets[2], diagnostics=True), timeout=5)
        assert busy["reason"] == "BUSY"
        assert busy["status"] == "UNAVAILABLE" and busy["items"] == []
        assert busy["diagnostics"]["search_count"] == 0
        assert datetime.fromisoformat(busy["expires_at"]) - wall[0] == timedelta(seconds=5)
        assert svc.cache[targets[2].digest][0] == mono[0] + 5
        assert svc.blocked_until == 0.0
        assert len(client.calls) == svc.calls_used == 2
    finally:
        release.set()
        completed = await asyncio.gather(*active)

    assert all(result["status"] == "AVAILABLE" for result in completed)
    assert len(client.calls) == svc.calls_used == 4
    assert (await svc.get(targets[2]))["reason"] == "BUSY"
    assert len(client.calls) == 4
    wall[0] += timedelta(seconds=5, milliseconds=1)
    mono[0] += 5.001
    assert (await svc.get(targets[2]))["status"] == "AVAILABLE"
    assert len(client.calls) == svc.calls_used == 6
    assert svc.blocked_until == 0.0 and not svc.inflight


@pytest.mark.asyncio
async def test_gone_item_is_rejected_while_other_exact_listings_remain_available():
    rows = [{**detail(1), "error": EbayApiError("gone", status_code=404)}, detail(2)]
    svc = service(FakeClient(details=rows))
    result = await svc.get(context.edition_target(ROW), diagnostics=True)
    assert result["item_count"] == 1
    assert result["diagnostics"]["candidates"][0]["reason"] == "ITEM_NO_LONGER_AVAILABLE"


@pytest.mark.asyncio
async def test_provider_diagnostics_report_rejections_without_raw_payload_or_tokens():
    row = {**detail(), "access_token": "must-not-leak", "price": {"currency": "USD", "value": "12"}}
    result = await service(FakeClient(details=[row])).get(context.edition_target(ROW), diagnostics=True)
    assert result["status"] == "UNAVAILABLE"
    assert result["diagnostics"]["candidates"][0]["reason"] == "INVALID_GBP_PRICE"
    assert result["diagnostics"]["candidates"][0]["identifiers"] == ["9781427800022"]
    assert "must-not-leak" not in json.dumps(result)


@pytest.mark.asyncio
async def test_mixed_isbn_upc_diagnostics_preserve_public_identifiers_without_relaxing_match():
    row = {**detail(), "product": {"gtins": ["9781427800022", "782009000000"],
                                   "access_token": "must-not-leak"}}
    result = await service(FakeClient(details=[row])).get(context.edition_target(ROW), diagnostics=True)
    assert result["status"] == "UNAVAILABLE" and result["items"] == []
    diagnostic = result["diagnostics"]["candidates"][0]
    assert diagnostic["identifiers"] == ["INVALID_OR_AMBIGUOUS"]
    assert diagnostic["raw_identifiers"] == {"product.gtins": ["9781427800022", "782009000000"]}
    assert "must-not-leak" not in json.dumps(result)


def test_raw_identifier_diagnostics_are_bounded_strings_from_fixed_public_fields():
    row = {**detail(), "gtin": {"private_token": "must-not-leak"},
           "product": {"gtins": ["x" * 100, 123, "9781427800022", "ignored-fourth"],
                       "private_token": "must-not-leak"},
           "localizedAspects": [{"name": "ISBN", "value": "z" * 100},
                                {"name": "private_token", "value": "must-not-leak"}]}
    diagnostic = context._diagnostic(row, row["itemId"], "INVALID_IDENTIFIERS")
    assert diagnostic["raw_identifiers"] == {
        "product.gtins": ["x" * 80, "9781427800022"], "aspects.isbn": ["z" * 80]}
    assert "must-not-leak" not in json.dumps(diagnostic)


def request_fixture(*, enabled=True):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db_pool=object(),
        settings=SimpleNamespace(book_ebay_context_enabled=enabled))), state=SimpleNamespace(request_id="request-1"))


def patch_database(monkeypatch, rows, *, deny=False):
    state = {"in_transaction": False, "access_checks": 0, "reads": 0}
    class Connection:
        async def fetchrow(self, query, catalogue_id):
            assert state["in_transaction"]
            assert query == context.TARGET_SQL and catalogue_id == UUID(CATALOGUE_ID)
            index = min(state["reads"], len(rows) - 1)
            state["reads"] += 1
            return rows[index]
    @asynccontextmanager
    async def connection(*args, **kwargs):
        assert kwargs["readonly_snapshot"] is True
        assert not state["in_transaction"]
        state["in_transaction"] = True
        try:
            yield Connection()
        finally:
            state["in_transaction"] = False
    async def access(conn):
        assert state["in_transaction"]
        state["access_checks"] += 1
        if deny:
            raise HTTPException(403, "No active owner membership")
        return {"owner_id": "owner-1"}
    monkeypatch.setattr(context, "user_connection", connection)
    monkeypatch.setattr(context, "current_access_context", access)
    return state


@pytest.mark.asyncio
async def test_endpoint_releases_read_transaction_before_provider_and_rechecks_access(monkeypatch):
    state = patch_database(monkeypatch, [ROW, ROW])
    request = request_fixture()
    class Service:
        async def get(self, target):
            assert state["in_transaction"] is False
            return context._empty(target, status="UNAVAILABLE", reason="NO_EXACT_ACTIVE_LISTINGS", now=NOW)
    request.app.state.book_ebay_context_service = Service()
    response = await context.book_listing_context(UUID(CATALOGUE_ID), request, SimpleNamespace(user_id=UUID(int=1)))
    assert response.status_code == 200
    assert state["access_checks"] == state["reads"] == 2
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_disabled_endpoint_still_checks_membership_without_provider(monkeypatch):
    state = patch_database(monkeypatch, [ROW])
    response = await context.book_listing_context(UUID(CATALOGUE_ID), request_fixture(enabled=False), SimpleNamespace(user_id=UUID(int=1)))
    assert json.loads(response.body)["status"] == "DISABLED"
    assert state["access_checks"] == state["reads"] == 1


@pytest.mark.asyncio
async def test_revoked_owner_cannot_load_shared_cached_provider_context(monkeypatch):
    state = patch_database(monkeypatch, [ROW], deny=True)
    with pytest.raises(HTTPException) as error:
        await context.book_listing_context(UUID(CATALOGUE_ID), request_fixture(), SimpleNamespace(user_id=UUID(int=1)))
    assert error.value.status_code == 403
    assert state["reads"] == 0


@pytest.mark.asyncio
async def test_identity_edit_during_provider_io_discards_old_listing_context(monkeypatch):
    patch_database(monkeypatch, [ROW, {**ROW, "version": 2}])
    request = request_fixture()
    class Service:
        async def get(self, target):
            value = context._empty(target, status="AVAILABLE", reason="MATCH", now=NOW)
            value.update(items=[{"title": "must-not-return-old-edition"}], item_count=1)
            return value
    request.app.state.book_ebay_context_service = Service()
    result = json.loads((await context.book_listing_context(UUID(CATALOGUE_ID), request, SimpleNamespace(user_id=UUID(int=1)))).body)
    assert result["reason"] == "EDITION_CHANGED"
    assert result["status"] == "UNAVAILABLE"
    assert result["items"] == []
