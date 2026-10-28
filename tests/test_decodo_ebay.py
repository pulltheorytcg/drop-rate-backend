import asyncio
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.decodo_ebay import DecodoEbaySoldClient, DecodoError, parse_sold_html

NOW = datetime(2026, 10, 28, 20, tzinfo=timezone.utc)


def card(*, title="Charizard Base Set 4/102 Holo English Near Mint",
         price="£120.00", date="Sold 27 Oct 2026", extra="", item="123456789012",
         shipping="Free delivery", style="s-item"):
    return f'''<li class="{style}">
      <a href="https://www.ebay.co.uk/itm/name/{item}?track=x">
      <h3 class="{style}__title">{title}</h3></a>
      <span class="{style}__price">{price}</span><span>{date}</span>
      <span class="{style}__shipping">{shipping}</span>{extra}</li>'''


def page(*cards):
    return "<html><title>eBay sold results</title><body><ul>" + "".join(cards) + "</ul></body></html>"


def test_extracts_dated_sale_and_preserves_unknown_shipping():
    row = parse_sold_html(page(card(shipping="Postage not specified")), now=NOW)["results"][0]
    assert row["sale_price"] == "120.00"
    assert row["shipping_price"] is None
    assert row["date_sold"] == "2026-10-27T00:00:00+00:00"
    assert row["provider"] == "DECODO"
    assert row["item_link"] == "https://www.ebay.co.uk/itm/123456789012"
    assert row["price_basis"] == "PUBLIC_SOLD_DISPLAY"


@pytest.mark.parametrize("change", [
    {"extra": "Best offer accepted"}, {"price": "<s>£120.00</s>"},
    {"date": "Completed 27 Oct 2026"}, {"date": "99 sold"},
    {"date": "Sold 27 Oct"}, {"date": "Sold 27 Oct 2027"},
    {"date": "Sold 27 Jan 2026"}, {"price": "£120.00 to £150.00"},
    {"price": "US $120.00"}, {"price": "£0.00"}, {"title": "Charizard card bundle"},
    {"title": "Charizard proxy"}, {"title": "Shop on eBay"},
    {"item": "not-an-item"},
])
def test_rejects_unsold_ambiguous_stale_and_nonstandard(change):
    assert parse_sold_html(page(card(**change)), now=NOW)["results"] == []


@pytest.mark.parametrize("date", [
    "Not Sold 27 Oct 2026",
    "NOT YET SOLD 27 Oct 2026",
    "Unsold: previously Sold 27 Oct 2026",
])
def test_negative_sale_labels_cannot_become_sold_evidence(date):
    result = parse_sold_html(page(card(date=date)), now=NOW)
    assert result["cards_seen"] == 1
    assert result["results"] == []
    assert result["rejected"]["MISSING_STALE_OR_FUTURE_SALE_DATE"] == 1


def test_valueless_class_does_not_break_a_recognised_sale_card():
    result = parse_sold_html(page(card(extra="<span class>Seller details</span>")), now=NOW)
    assert len(result["results"]) == 1
    assert result["results"][0]["item_id"] == "123456789012"


def test_valueless_class_does_not_turn_unknown_markup_into_empty_success():
    with pytest.raises(DecodoError, match="UNRECOGNISED_SEARCH_HTML"):
        parse_sold_html("<html><title>eBay</title><div class>Unexpected layout</div></html>", now=NOW)


def test_valueless_form_action_still_checks_login_gate():
    with pytest.raises(DecodoError, match="TARGET_ACCESS_GATE"):
        parse_sold_html('<form action id="signin-form"></form>', now=NOW)


def test_new_card_class_and_english_month_first_date():
    row = parse_sold_html(page(card(style="s-card", date="Sold Oct 27, 2026", shipping="+£3.50 postage")), now=NOW)["results"][0]
    assert row["shipping_price"] == "3.50"


def test_duplicate_page_item_does_not_create_another_sale():
    result = parse_sold_html(page(card(), card()), now=NOW)
    assert len(result["results"]) == 1
    assert result["rejected"]["DUPLICATE_ITEM"] == 1


def test_conflicting_duplicate_prices_are_quarantined():
    result = parse_sold_html(page(card(), card(price="£90.00")), now=NOW)
    assert result["results"] == []
    assert result["rejected"]["CONFLICTING_ITEM"] == 1


@pytest.mark.parametrize("content,code", [
    ("<title>Sign in | eBay</title>", "TARGET_ACCESS_GATE"),
    ("<title>Pardon Our Interruption</title>", "TARGET_ACCESS_GATE"),
    ('<form action="https://signin.ebay.co.uk/ws/eBayISAPI.dll"></form>', "TARGET_ACCESS_GATE"),
    ("<html>different search structure</html>", "UNRECOGNISED_SEARCH_HTML"),
])
def test_gates_and_markup_drift_are_errors(content, code):
    with pytest.raises(DecodoError, match=code):
        parse_sold_html(content, now=NOW)


def test_real_no_results_and_ordinary_signin_link():
    assert parse_sold_html('<a href="/signin">Sign in</a>0 results', now=NOW)["results"] == []


class Clock:
    def __init__(self):
        self.now = 0
    def time(self):
        return self.now
    async def sleep(self, seconds):
        self.now += seconds


def success(request):
    return httpx.Response(200, json={"results": [{"status_code": 200, "content": "0 results"}]})


@pytest.mark.asyncio
async def test_rate_ceiling_and_bounded_request_budget():
    clock, times = Clock(), []
    def transport(request):
        times.append(clock.time())
        return success(request)
    client = DecodoEbaySoldClient(api_key="test-key", requests_per_second=10, max_requests=3,
        transport=httpx.MockTransport(transport), clock=clock.time, sleep=clock.sleep)
    await asyncio.gather(*(client.sold(query="card") for _ in range(3)))
    assert all(b-a >= .099 for a,b in zip(times, times[1:]))
    with pytest.raises(DecodoError, match="REQUEST_BUDGET"):
        await client.sold(query="card")
    assert len(times) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_error_stops_run_without_retry_or_secret_leak(status):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(status, headers={"retry-after": "60"}, text="private-key-do-not-log")
    client = DecodoEbaySoldClient(api_key="private-key-do-not-log", transport=httpx.MockTransport(transport))
    with pytest.raises(DecodoError) as error:
        await client.sold(query="card")
    assert error.value.status == status
    assert "private-key" not in str(error.value)
    with pytest.raises(DecodoError, match="RUN_STOPPED"):
        await client.sold(query="another card")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fixed_provider_and_ebay_hosts_and_no_session_forwarding():
    calls = []
    def transport(request):
        calls.append(request)
        return success(request)
    client = DecodoEbaySoldClient(api_key="test-key", transport=httpx.MockTransport(transport))
    await client.sold(query="https://internal.invalid &LH_Sold=0")
    request = calls[0]
    assert str(request.url) == "https://data.decodo.com/v1/scrape"
    body = json.loads(request.content)
    target = urlparse(body["url"])
    assert target.hostname == "www.ebay.co.uk"
    assert parse_qs(target.query)["LH_Sold"] == ["1"]
    assert parse_qs(target.query)["_nkw"] == ["https://internal.invalid &LH_Sold=0"]
    assert not {"cookies", "headers", "force_cookies", "force_headers", "session_id"} & body.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,code", [
    ({"results": []}, "PROVIDER_SCHEMA_CHANGED"),
    ({"results": [{"status_code": 403, "content": "blocked"}]}, "TARGET_HTTP_ERROR"),
    ({"results": [{"status_code": 200, "content": "<title>Sign in</title>"}]}, "TARGET_ACCESS_GATE"),
    ({"results": [{"status_code": 200, "content": None}]}, "INVALID_HTML_SIZE"),
])
async def test_provider_wrapper_and_target_errors_fail_closed(payload, code):
    client = DecodoEbaySoldClient(api_key="test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    with pytest.raises(DecodoError, match=code):
        await client.sold(query="card")


@pytest.mark.parametrize("rps", [0, 11, True, float("nan"), float("inf")])
def test_invalid_rate_rejected(rps):
    with pytest.raises(ValueError):
        DecodoEbaySoldClient(api_key="test", requests_per_second=rps)


@pytest.mark.asyncio
async def test_conflicting_id_cannot_reappear_on_later_page():
    today = datetime.now(timezone.utc).strftime("Sold %d %b %Y")
    contents = [page(card(date=today), card(date=today, price="£90.00")),
                page(card(date=today))]
    clock = Clock()
    client = DecodoEbaySoldClient(api_key="test", clock=clock.time, sleep=clock.sleep,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            "results": [{"status_code": 200, "content": contents.pop(0)}]})))
    result = await client.sold(query="Charizard", max_pages=2)
    assert result["results"] == []
    assert result["_usage"]["requests_sent"] == 2


