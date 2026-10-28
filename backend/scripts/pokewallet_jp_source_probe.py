"""Opt-in, read-only inspection of negative-ID Japanese PokéWallet sets.

At most three free API requests: /sets, then page one for up to two sets.
No database, pricing adapter, currency conversion, paid endpoint or writes.
Incomplete results provide page counts only, never printing-match evidence.
Reference: https://pokewallet.io/api-docs (reviewed 28 October 2026).
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re
from urllib.parse import urlsplit

import httpx


BASE_URL = "https://api.pokewallet.io"
MAX_REQUESTS = 3
MAX_BYTES = 2_000_000
QUOTA_RESERVE = 5
CODE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,17}\Z")
NEGATIVE_ID = re.compile(r"-[1-9][0-9]{0,9}\Z")
CARD_ID = re.compile(r"(?:pk_[a-fA-F0-9]{32,128}|[a-fA-F0-9]{64})\Z")
FRACTION = re.compile(r"0*[1-9][0-9]{0,3}/0*[1-9][0-9]{0,3}\Z")
PRICE_FIELDS = ("avg", "low", "avg1", "avg7", "avg30", "trend")
KNOWN_PRICE_KEYS = frozenset((*PRICE_FIELDS, "variant_type", "updated_at"))


class ProbeError(ValueError):
    """Only literal, sanitized diagnostic codes may be used as messages."""


def safe_text(value, secret, *, limit=160):
    if not isinstance(value, str) or len(value) > limit:
        return None
    if (secret in value or re.search(r"pk_(?:live|test)_|bearer\s|api[_ -]?key|authorization", value, re.I)
            or any(ord(char) < 32 for char in value)):
        return None
    return value


def positive(value):
    if type(value) not in (int, float, str) or len(str(value)) > 64:
        return False
    try:
        amount = Decimal(str(value))
        return amount.is_finite() and amount > 0
    except InvalidOperation:
        return False


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.isoformat()


def single_url(value):
    if not isinstance(value, str) or len(value) > 1000:
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == "https" and url.netloc in {"cardmarket.com", "www.cardmarket.com"}
                and not url.query and not url.fragment
                and bool(re.fullmatch(r"/(?:en|it|de|fr|es)/Pokemon/Products/Singles/[^/]+/[^/]+", url.path, re.I)))
    except ValueError:
        return False


class ProbeClient:
    def __init__(self, http, key):
        self.http, self.key, self.requests = http, key, 0
        self.remaining = None

    async def get(self, path, params=None):
        if not (path == "/sets" and params is None or path == "/search" and isinstance(params, dict)
                and set(params) == {"q", "page", "limit"} and CODE.fullmatch(str(params["q"]))
                and params["page"] == 1 and params["limit"] == 100):
            raise ProbeError("UNREVIEWED_ENDPOINT")
        if self.requests >= MAX_REQUESTS:
            raise ProbeError("REQUEST_BUDGET_EXHAUSTED")
        if self.remaining is not None and min(self.remaining) <= QUOTA_RESERVE:
            raise ProbeError("PROVIDER_BUDGET_LOW")
        self.requests += 1
        async with self.http.stream("GET", BASE_URL + path, params=params,
                headers={"X-API-Key": self.key, "Accept": "application/json"},
                follow_redirects=False) as response:
            if response.status_code == 429:
                raise ProbeError("RATE_LIMITED")
            if response.status_code != 200:
                raise ProbeError("UPSTREAM_HTTP_" + str(response.status_code))
            remaining = [response.headers.get(name) for name in
                         ("X-RateLimit-Remaining-Hour", "X-RateLimit-Remaining-Day")]
            if any(value is None or not re.fullmatch(r"[0-9]{1,8}", value) for value in remaining):
                raise ProbeError("QUOTA_HEADERS_UNAVAILABLE")
            self.remaining = tuple(int(value) for value in remaining)
            if min(self.remaining) < QUOTA_RESERVE:
                raise ProbeError("PROVIDER_BUDGET_LOW")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ProbeError("RESPONSE_TOO_LARGE")
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError):
            raise ProbeError("INVALID_JSON") from None
        if not isinstance(value, dict):
            raise ProbeError("INVALID_SCHEMA")
        return value


def select_sets(body, requested, secret):
    rows = body.get("data")
    if (body.get("success") is not True or not isinstance(rows, list) or len(rows) > 5000
            or any(not isinstance(row, dict) for row in rows)
            or type(body.get("total")) is not int or body["total"] != len(rows)):
        raise ProbeError("INCOMPLETE_SET_LIST")
    japanese = [row for row in rows if row.get("language") == "jap"]
    negative = [row for row in japanese if NEGATIVE_ID.fullmatch(str(row.get("set_id", "")))]
    counts = Counter(str(row.get("set_code", "")).casefold() for row in japanese)
    ids = Counter(str(row.get("set_id", "")) for row in rows)
    candidates = [row for row in negative if CODE.fullmatch(str(row.get("set_code", "")))
                  and counts[row["set_code"].casefold()] == 1 and ids[str(row["set_id"])] == 1
                  and type(row.get("card_count")) is int and 0 < row["card_count"] <= 100_000]
    candidates.sort(key=lambda row: (row["set_code"].casefold() != "adv2",
                                    row["card_count"] > 100, row["set_code"].casefold()))
    counts_report = {"sets": len(rows), "japanese_sets": len(japanese),
                     "negative_id_japanese_sets": len(negative), "unique_code_candidates": len(candidates)}
    if requested:
        selected = [next((row for row in candidates if row["set_code"].casefold() == code), None)
                    for code in requested]
        if any(row is None for row in selected):
            raise ProbeError("TARGET_NOT_IN_NEGATIVE_JAPANESE_SETS")
    else:
        selected = candidates[:2]
    fields = []
    for row in selected:
        fields.append({"set_id": str(row["set_id"]), "set_code": row["set_code"],
                       "name": safe_text(row.get("name"), secret), "language": "jap",
                       "card_count": row["card_count"],
                       "release_date": safe_text(row.get("release_date"), secret, limit=80)})
    return counts_report, fields


def inspect_page(body, target, secret):
    rows, paging = body.get("results"), body.get("pagination")
    if (str(body.get("query", "")).casefold() != target["set_code"].casefold()
            or not isinstance(rows, list) or not isinstance(paging, dict)
            or any(not isinstance(row, dict) for row in rows)):
        raise ProbeError("SEARCH_SCHEMA")
    total, pages = paging.get("total"), paging.get("total_pages")
    if (type(total) is not int or not 0 <= total <= 100_000
            or type(pages) is not int or pages != (total + 99) // 100
            or type(paging.get("page")) is not int or paging["page"] != 1
            or type(paging.get("limit")) is not int or paging["limit"] != 100 or len(rows) != min(100, total)
            or (isinstance(body.get("metadata"), dict) and body["metadata"].get("truncated") is True)):
        raise ProbeError("INCOMPLETE_SEARCH_PAGE")
    exact = [row for row in rows if isinstance(row.get("card_info"), dict)
             and row["card_info"].get("product_type") == "card"
             and str(row["card_info"].get("set_id", "")) == target["set_id"]]
    valid_ids = all(CARD_ID.fullmatch(str(row.get("id", ""))) for row in rows)
    complete = (pages <= 1 and len(exact) == target["card_count"] and valid_ids
                and len({row.get("id") for row in rows}) == len(rows)
                and all(str(row["card_info"].get("set_code", "")).casefold()
                        in {target["set_code"].casefold(), target["set_id"]} for row in exact))
    shape = Counter({key: 0 for key in ("same_set_cards", "numeric_only_numbers", "full_collector_fractions",
                    "cardmarket_missing", "empty_cardmarket_prices", "invalid_cardmarket_single_urls",
                    "cards_with_positive_trend", "cards_with_positive_avg30", "unknown_price_variants")})
    preview = []
    for row in exact:
        info, market = row["card_info"], row.get("cardmarket")
        number = str(info.get("card_number", ""))
        shape["same_set_cards"] += 1
        shape["numeric_only_numbers"] += number.isdigit()
        shape["full_collector_fractions"] += bool(FRACTION.fullmatch(number))
        prices = market.get("prices") if isinstance(market, dict) else None
        shape["cardmarket_missing"] += not isinstance(market, dict)
        shape["empty_cardmarket_prices"] += not isinstance(prices, list) or not prices
        safe_prices = [price for price in prices if isinstance(price, dict)] if isinstance(prices, list) else []
        url_ok = single_url(market.get("product_url")) if isinstance(market, dict) else False
        shape["invalid_cardmarket_single_urls"] += not url_ok
        shape["cards_with_positive_trend"] += any(positive(price.get("trend")) for price in safe_prices)
        shape["cards_with_positive_avg30"] += any(positive(price.get("avg30")) for price in safe_prices)
        shape["unknown_price_variants"] += sum(price.get("variant_type") not in ("normal", "holo")
                                               for price in safe_prices)
        if complete and len(preview) < 5:
            preview.append({"id": row["id"], "set_id": target["set_id"],
                "set_code": safe_text(info.get("set_code"), secret, limit=20),
                "name": safe_text(info.get("name"), secret),
                "card_number": safe_text(info.get("card_number"), secret, limit=30),
                "cardmarket_single_url_valid": url_ok, "price_rows": len(safe_prices),
                "prices": [{"keys": sorted(KNOWN_PRICE_KEYS.intersection(price)),
                            "unknown_key_count": len(set(price) - KNOWN_PRICE_KEYS),
                            "variant_type": price.get("variant_type") if price.get("variant_type") in ("normal", "holo") else "OTHER",
                            "positive": {key: positive(price.get(key)) for key in PRICE_FIELDS},
                            "updated_at": timestamp(price.get("updated_at"))} for price in safe_prices[:4]]})
    return {"set": target, "search_total": total, "search_pages": pages,
            "page_rows": len(rows), "complete_source_set": complete,
            "scope": "COMPLETE_SOURCE_SET" if complete else "PAGE_ONLY",
            "printing_matches_claimed": 0, "page_shape": dict(shape), "preview": preview}


async def run_probe(*, execute=False, set_codes=None, api_key=None, http_client=None):
    report = {"event": "DROP_RATE_POKEWALLET_JP_SOURCE_PROBE", "version": 1,
              "checked_at": datetime.now(timezone.utc).isoformat(), "requests": 0,
              "persisted": False, "database_writes": 0, "physical_valuation_eligible": False,
              "targets": [], "status": "SKIPPED", "reason": "OPT_IN_REQUIRED"}
    if execute is not True:
        return report
    requested = list(set_codes or [])
    if (len(requested) > 2 or any(not isinstance(code, str) or not CODE.fullmatch(code) for code in requested)
            or len({code.casefold() for code in requested}) != len(requested)):
        return {**report, "status": "UNAVAILABLE", "reason": "INVALID_SET_CODES"}
    key = api_key if api_key is not None else os.getenv("TCG_POKEWALLET_API_KEY", "")
    if not isinstance(key, str) or not re.fullmatch(r"pk_live_[A-Za-z0-9_-]{8,240}", key):
        return {**report, "status": "UNAVAILABLE", "reason": "LIVE_API_KEY_REQUIRED"}
    owns_http = http_client is None
    http, client = http_client, None
    try:
        if http is None:
            http = httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), follow_redirects=False)
        client = ProbeClient(http, key)
        async with asyncio.timeout(40):
            sets = await client.get("/sets")
            summary, targets = select_sets(sets, [code.casefold() for code in requested], key)
            report["set_summary"] = summary
            report["selected_sets"] = targets
            for target in targets:
                payload = await client.get("/search", {"q": target["set_code"], "page": 1, "limit": 100})
                report["targets"].append(inspect_page(payload, target, key))
            report.update(status="COMPLETE", reason="DIAGNOSTICS_ONLY" if targets else "NO_NEGATIVE_ID_JAPANESE_TARGETS")
    except ProbeError as exc:
        report.update(status="INCOMPLETE", reason=str(exc))
    except Exception:
        # Never include exception strings, raw bodies, response headers or key.
        report.update(status="INCOMPLETE", reason="CONFIGURATION_OR_PROVIDER_FAILURE")
    finally:
        report["requests"] = client.requests if client is not None else 0
        if owns_http and http is not None:
            try:
                await http.aclose()
            except Exception:
                report.update(status="INCOMPLETE", reason="CONFIGURATION_OR_PROVIDER_FAILURE")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Allow at most three free, read-only requests")
    parser.add_argument("--set-code", action="append", default=[], help="Optional exact source Japanese code; maximum two")
    args = parser.parse_args(argv)
    print(json.dumps(asyncio.run(run_probe(execute=args.execute, set_codes=args.set_code)),
                     sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
