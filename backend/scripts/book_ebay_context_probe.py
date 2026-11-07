"""One opt-in official Browse probe for a pinned public catalogue edition.

No database, market ingestion, Trawl, Parse, price writes or media writes.
Omitting the exact ISBN flag skips the probe, including during normal deploys.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

from app.book_ebay_context import edition_target, normalize_isbn, service_from_settings
from app.settings import get_settings


PILOT_ISBN = "9781427800022"
PILOT = {
    "catalogue_id": "607ab7c5-4e33-5bd0-8725-640ccb506c98",
    "product_type": "COMIC", "system_code": "MANGA", "series_title": "+Anima",
    "issue_number": "1", "volume_identifier": "Paperback", "release_year": 2006,
    "language": "English", "barcode_gtin": PILOT_ISBN,
    "identity_status": "STRUCTURED", "profile_status": "STRUCTURED", "version": 1,
    "attributes": {"publisher": "TokyoPop", "book_format": "MANGA",
        "identity_source": "OPEN_LIBRARY_CATALOGUE",
        "source_url": "https://openlibrary.org/books/OL8537239M"},
}
NARUTO_PILOT_ISBN = "9781569319000"
NARUTO_PILOT = {
    "catalogue_id": "9264f778-e6a2-5f59-b0d2-23e8d725f4e5",
    "product_type": "COMIC", "system_code": "MANGA", "series_title": "Naruto",
    "issue_number": "1", "volume_identifier": None, "release_year": 2003,
    "language": "English", "barcode_gtin": NARUTO_PILOT_ISBN,
    "identity_status": "STRUCTURED", "profile_status": "STRUCTURED", "version": 1,
    "attributes": {"publisher": "VIZ Media", "book_format": "MANGA",
        "identity_source": "OFFICIAL_PUBLISHER_CATALOGUE",
        "source_url": "https://www.viz.com/manga-books/manga/naruto-volume-1-0/product/91"},
}
PINNED_PILOTS = {PILOT_ISBN: PILOT, NARUTO_PILOT_ISBN: NARUTO_PILOT}
PINNED_NARUTO_LISTING_IDS = {"298583744784", "800761400014"}


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isbn", default=os.getenv("TCG_BOOK_EBAY_CONTEXT_PROBE_ISBN"))
    parser.add_argument("--listing-id", help="Optional reviewed Naruto listing ID; never used by the catalogue endpoint")
    parser.add_argument("--title")
    parser.add_argument("--volume")
    parser.add_argument("--language")
    parser.add_argument("--binding")
    parser.add_argument("--publisher")
    return parser.parse_args(argv)


async def run_probe(args, *, settings=None):
    report = {"event": "DROP_RATE_BOOK_EBAY_CONTEXT_PROBE", "version": "book-ebay-context-v1",
              "persisted": False, "physical_valuation_eligible": False,
              "provider": "OFFICIAL_EBAY_BROWSE", "browse_calls": 0}
    if not args.isbn:
        return {**report, "status": "SKIPPED", "reason": "EXACT_ISBN_FLAG_NOT_SET"}
    pilot = PINNED_PILOTS.get(normalize_isbn(args.isbn))
    if pilot is None:
        return {**report, "status": "UNAVAILABLE", "reason": "PINNED_PILOT_ISBN_REQUIRED"}
    listing_id = getattr(args, "listing_id", None)
    if listing_id is not None and (not isinstance(listing_id, str) or pilot is not NARUTO_PILOT
                                   or listing_id not in PINNED_NARUTO_LISTING_IDS):
        return {**report, "status": "UNAVAILABLE", "reason": "PINNED_LISTING_ID_REQUIRED"}
    expected = {"title": pilot["series_title"], "volume": pilot["issue_number"],
                "language": pilot["language"], "binding": pilot["volume_identifier"],
                "publisher": pilot["attributes"]["publisher"]}
    if any(getattr(args, field) is not None and getattr(args, field) != value for field, value in expected.items()):
        return {**report, "status": "UNAVAILABLE", "reason": "PILOT_IDENTITY_CONFLICT"}
    target = edition_target(pilot)
    if target is None:
        return {**report, "status": "UNAVAILABLE", "reason": "PILOT_IDENTITY_UNAVAILABLE"}
    try:
        settings = settings or get_settings()
        service = service_from_settings(settings)
        result = (await service.probe_listing(target, f"v1|{listing_id}|0") if listing_id is not None
                  else await service.get(target, diagnostics=True))
        return {**report, "status": result["status"], "reason": result["reason"],
                "target_source": "PINNED_PUBLIC_CATALOGUE_FIXTURE_20261027",
                "source_url": pilot["attributes"]["source_url"],
                "requested_listing_id": listing_id,
                "browse_calls": service.calls_used, "result": result}
    except Exception:
        # Settings failures and provider exceptions must never print tokens,
        # credentials, connection strings, exception bodies or raw responses.
        return {**report, "status": "UNAVAILABLE", "reason": "PROBE_CONFIGURATION_OR_PROVIDER_FAILURE"}


def main(argv=None):
    report = asyncio.run(run_probe(arguments(argv)))
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    # The opt-in probe records evidence. Feature activation remains a separate
    # deployment decision; unavailable third-party data is not a fake success.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
