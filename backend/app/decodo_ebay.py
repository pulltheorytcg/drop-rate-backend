"""Bounded public eBay UK sold-page acquisition through Decodo Web Data API.

Returns the existing sold-client payload shape. It never writes prices, logs
credentials, supplies eBay cookies, or treats retrieval time as a sale date.
Live HTML compatibility must be demonstrated by the pilot before activation.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urlencode, urlparse

import httpx

ENDPOINT = "https://data.decodo.com/v1/scrape"
MAX_BYTES = 10_000_000


class DecodoError(RuntimeError):
    def __init__(self, code, *, status=None, retry_after=None):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    @property
    def classes(self):
        return set(self.attrs.get("class", "").split())

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.nodes()

    def text(self):
        if self.tag in {"script", "style", "noscript"}:
            return ""
        return " ".join(c.text() if isinstance(c, Node) else c for c in self.children).strip()


class Document(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)
            if len(self.stack) > 256:
                raise DecodoError("HTML_DEPTH_LIMIT")

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _field(node, classes):
    for item in node.nodes():
        if item.classes.intersection(classes):
            return " ".join(item.text().split())
    return ""


def _amount(text):
    # Reject converted ranges, multiple prices, dollar amounts and unknown units.
    match = re.fullmatch(r"\s*(?:£|GBP\s*)(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d{2}))?\s*", text)
    if not match:
        return None
    value = Decimal(match[1].replace(",", "") + "." + (match[2] or "00"))
    return format(value, ".2f") if 0 < value <= 10_000_000 else None


def _sale_date(text, now):
    found = re.search(r"\bSold\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})\b", text, re.I)
    if not found:
        return None
    raw = found[1].replace(",", "")
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%Y-%m-%d"):
        try:
            stamp = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if now - timedelta(days=90) <= stamp <= now:
            return stamp.isoformat()
    return None


def _item_url(node):
    for child in node.nodes():
        if child.tag != "a":
            continue
        url = urlparse(child.attrs.get("href", ""))
        if url.scheme != "https" or url.hostname not in {"www.ebay.co.uk", "ebay.co.uk"}:
            continue
        match = re.fullmatch(r"/itm/(?:[^/]+/)?(\d{9,15})/?", url.path)
        if match:
            return match[1], "https://www.ebay.co.uk/itm/" + match[1]
    return None, None


def parse_sold_html(content, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_BYTES:
        raise DecodoError("INVALID_HTML_SIZE")
    root = Document(content).root
    nodes = list(root.nodes())
    title = " ".join(n.text() for n in nodes if n.tag == "title").casefold()
    if any(x in title for x in ("sign in", "signin", "pardon our interruption", "security measure", "robot check", "captcha", "access denied")):
        raise DecodoError("TARGET_ACCESS_GATE")
    if any(n.tag == "form" and ("signin.ebay." in n.attrs.get("action", "") or n.attrs.get("id") == "signin-form") for n in nodes):
        raise DecodoError("TARGET_ACCESS_GATE")
    cards = [n for n in nodes if n.classes.intersection({"s-item", "s-card"})]
    if not cards:
        # Unknown markup is an error, not a successful zero-result page.
        if re.search(r"\b(?:0 results|no exact matches found|no results found)\b", root.text(), re.I):
            return {"results": [], "rejected": {}, "cards_seen": 0}
        raise DecodoError("UNRECOGNISED_SEARCH_HTML")
    rows, rejected, conflicting = {}, Counter(), set()
    for card in cards:
        text = " ".join(card.text().split())
        if re.search(r"\bbest offer\b", text, re.I) or any(n.tag in {"s", "del"} or "STRIKETHROUGH" in n.classes for n in card.nodes()):
            rejected["HIDDEN_OR_AMBIGUOUS_SALE_PRICE"] += 1
            continue
        sold_at = _sale_date(text, now)
        if sold_at is None:
            rejected["MISSING_STALE_OR_FUTURE_SALE_DATE"] += 1
            continue
        price = _amount(_field(card, {"s-item__price", "s-card__price"}))
        item_id, url = _item_url(card)
        name = _field(card, {"s-item__title", "s-card__title"})
        if not price or not item_id or not name or "shop on ebay" in name.casefold():
            rejected["MISSING_ID_TITLE_OR_EXACT_GBP_PRICE"] += 1
            continue
        if re.search(r"\b(?:lot|bundle|playset|proxy|replica|custom|choose|pick)\b|\b\d+\s*(?:cards|pcs)\b", name, re.I):
            rejected["MULTI_ITEM_OR_NONSTANDARD"] += 1
            continue
        shipping_text = _field(card, {"s-item__shipping", "s-item__logisticsCost", "s-card__shipping"})
        shipping = None
        if re.search(r"\bfree\s+(?:postage|delivery|shipping)\b", shipping_text, re.I):
            shipping = "0.00"
        elif match := re.fullmatch(r"\+?\s*((?:£|GBP\s*)[\d,.]+)\s+(?:postage|delivery|shipping)", shipping_text, re.I):
            shipping = _amount(match[1])
        row = {
            "item_id": item_id, "item_link": url, "title": name,
            "sale_price": price, "shipping_price": shipping, "currency": "GBP",
            "date_sold": sold_at,
            "condition_raw": _field(card, {"SECONDARY_INFO", "s-card__subtitle"}) or None,
            "provider": "DECODO", "price_basis": "PUBLIC_SOLD_DISPLAY",
            "sold_date_precision": "DAY", "shipping_known": shipping is not None,
        }
        if item_id in rows and rows[item_id] != row:
            conflicting.add(item_id)
        elif item_id in rows:
            rejected["DUPLICATE_ITEM"] += 1
        rows.setdefault(item_id, row)
    for item_id in conflicting:
        rows.pop(item_id, None)
        rejected["CONFLICTING_ITEM"] += 1
    return {"results": list(rows.values()), "rejected": dict(rejected), "cards_seen": len(cards),
            "conflicting_ids": sorted(conflicting)}


class DecodoEbaySoldClient:
    """Use one client per bounded run; its limiter/budget cover every page.

    No automatic retry: an ambiguous timeout can still have consumed a credit.
    Auth, rate limits, target gates and schema drift stop the entire run.
    """
    def __init__(self, *, api_key, requests_per_second=1.0, max_requests=200,
                 javascript=False, transport=None, clock=time.monotonic, sleep=asyncio.sleep):
        if not isinstance(api_key, str) or not api_key.strip() or "\n" in api_key or "\r" in api_key:
            raise ValueError("A server-side Decodo API key is required")
        if isinstance(requests_per_second, bool) or not 0 < requests_per_second <= 10:
            raise ValueError("Decodo rate must be greater than zero and at most 10")
        if type(max_requests) is not int or not 1 <= max_requests <= 200:
            raise ValueError("Pilot request budget must be 1..200")
        self._key, self._transport = api_key.strip(), transport
        self._interval, self._budget = 1 / requests_per_second, max_requests
        self._javascript, self._clock, self._sleep = javascript, clock, sleep
        self._lock, self._next = asyncio.Lock(), 0.0
        self.requests_sent, self._stopped = 0, False

    async def _reserve(self):
        async with self._lock:
            if self._stopped:
                raise DecodoError("RUN_STOPPED")
            if self.requests_sent >= self._budget:
                raise DecodoError("REQUEST_BUDGET_EXHAUSTED")
            delay = self._next - self._clock()
            if delay > 0:
                await self._sleep(delay)
            self._next = self._clock() + self._interval
            self.requests_sent += 1

    async def _page(self, query, page):
        await self._reserve()
        url = "https://www.ebay.co.uk/sch/i.html?" + urlencode({
            "_nkw": query, "LH_Sold": "1", "LH_Complete": "1",
            "_sop": "13", "_ipg": "60", "_pgn": str(page),
        })
        body = {"url": url, "geo": "GB", "locale": "en-GB", "proxy_pool": "standard"}
        if self._javascript:
            body["headless"] = "html"
        try:
            async with httpx.AsyncClient(timeout=45, transport=self._transport, follow_redirects=False, trust_env=False) as http:
                response = await http.post(ENDPOINT, json=body, headers={
                    "Authorization": "Bearer " + self._key, "Accept": "application/json",
                })
            if response.status_code != 200:
                wait = response.headers.get("retry-after")
                wait = int(wait) if wait and wait.isdigit() else None
                raise DecodoError("PROVIDER_HTTP_ERROR", status=response.status_code, retry_after=wait)
            if len(response.content) > MAX_BYTES:
                raise DecodoError("PROVIDER_RESPONSE_TOO_LARGE")
            payload = response.json()
            results = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
                raise DecodoError("PROVIDER_SCHEMA_CHANGED")
            result = results[0]
            if result.get("status_code") != 200:
                raise DecodoError("TARGET_HTTP_ERROR", status=result.get("status_code"))
            parsed = parse_sold_html(result.get("content"))
            return parsed
        except DecodoError:
            self._stopped = True
            raise
        except (httpx.HTTPError, ValueError, RecursionError):
            self._stopped = True
            raise DecodoError("PROVIDER_TRANSPORT_OR_PAYLOAD_ERROR") from None

    async def sold(self, *, query, max_pages=1):
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("A bounded search query is required")
        if type(max_pages) is not int or not 1 <= max_pages <= 2:
            raise ValueError("Pilot max_pages must be 1 or 2")
        rows, rejected, conflicts, seen = {}, Counter(), set(), 0
        start = self.requests_sent
        for page in range(1, max_pages + 1):
            data = await self._page(query.strip(), page)
            seen += data["cards_seen"]
            rejected.update(data["rejected"])
            conflicts.update(data.get("conflicting_ids", []))
            for row in data["results"]:
                key = row["item_id"]
                if key in rows and rows[key] != row:
                    conflicts.add(key)
                elif key in rows:
                    rejected["DUPLICATE_ITEM"] += 1
                rows.setdefault(key, row)
            if not data["cards_seen"]:
                break
        for key in conflicts:
            rows.pop(key, None)
            rejected["CONFLICTING_ITEM"] += 1
        return {
            "site": "EBAY_GB", "currency": "GBP", "provider": "DECODO",
            "results": list(rows.values()), "rejected": dict(rejected),
            "cards_seen": seen, "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "_usage": {"requests_sent": self.requests_sent - start, "charged": None},
        }

