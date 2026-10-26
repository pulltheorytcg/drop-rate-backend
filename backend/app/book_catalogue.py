"""Publisher edition facts for book browsing; never physical-copy approval."""
from __future__ import annotations

import json
from urllib.parse import urlencode

from pydantic import ValidationError

from .comic_identity import ComicPrintingCreate
from .book_artwork import book_cover_reference


def publisher_page(value):
    from .book_research import publisher_source
    return value if isinstance(value, str) and publisher_source(value) else None


async def with_book_details(connection, rows):
    """One bounded read; return book fields only, never private source metadata."""
    items = [dict(row) for row in rows]
    books = [row for row in items if row.get("product_type") == "COMIC" and row.get("catalogue_id")]
    if not books:
        return items
    records = await connection.fetch("""select b.*,pr.identity_status as profile_status,pr.release_date as profile_release_date
        from tcg.comic_printing_details b
        join tcg.catalogue_product_profiles pr on pr.catalogue_id=b.catalogue_id
        and pr.system_code=b.system_code and pr.collectible_type='COMIC'
        where b.catalogue_id=any($1::uuid[])""", list({row["catalogue_id"] for row in books}))
    by_id = {str(row["catalogue_id"]): dict(row) for row in records}
    for item in books:
        book = by_id.get(str(item["catalogue_id"]))
        if not book:
            continue
        attributes = book.get("attributes") or {}
        if isinstance(attributes, str):
            attributes = json.loads(attributes)
        if not isinstance(attributes, dict):
            continue
        fields = {key: book.get(key) for key in ComicPrintingCreate.model_fields}
        fields.update(publisher=attributes.get("publisher"), book_format=attributes.get("book_format"))
        try:
            details = ComicPrintingCreate.model_validate(fields).model_dump()
        except ValidationError:
            continue
        item["book_details"] = {**details, "language": item.get("language")}
        item["book_market_status"] = ("AVAILABLE" if item.get("market_value_minor") is not None else
            "PRINTING_REVIEW_REQUIRED" if (book.get("identity_status") != "VERIFIED"
                or book.get("profile_status") != "VERIFIED" or not details.get("printing_number")
                or (details["book_format"] == "SINGLE_ISSUE" and not details.get("cover_code")))
            else "SOLD_EVIDENCE_PENDING")
        search = " ".join(str(value) for value in (
            details["series_title"], "Vol" if details["system_code"] == "MANGA" else "Issue",
            details["issue_number"], details.get("barcode_gtin"), details.get("publisher"),
            item.get("language"), details.get("release_year"),
            f"printing {details['printing_number']}" if details.get("printing_number") else None,
            details.get("cover_code")) if value)
        item["book_sold_search_url"] = "https://www.ebay.co.uk/sch/i.html?" + urlencode({
            "_nkw": search, "LH_Sold": "1", "LH_Complete": "1"})
        if (book.get("identity_status") in {"STRUCTURED", "VERIFIED"}
                and book.get("profile_status") in {"STRUCTURED", "VERIFIED"}
                and attributes.get("identity_source") == "OFFICIAL_PUBLISHER_CATALOGUE"):
            source = publisher_page(attributes.get("source_url"))
            if source:
                item["publisher_source_url"] = source
                item["book_reference_scope"] = "PUBLISHER_EDITION"
        receipt = attributes.get("catalogue_import")
        if (book.get("identity_status") in {"STRUCTURED", "VERIFIED"}
                and book.get("profile_status") in {"STRUCTURED", "VERIFIED"}
                and attributes.get("identity_source") == "GCD_CATALOGUE"
                and isinstance(receipt, dict) and receipt.get("provider") == "GCD"
                and receipt.get("version") == "book-bulk-v1"
                and receipt.get("metadata_license") == "https://creativecommons.org/licenses/by-sa/4.0/"):
            import re
            source = attributes.get("source_url", "")
            if re.fullmatch(r"https://www\.comics\.org/issue/[1-9][0-9]*/", source):
                item["book_data_attribution"] = {
                    "text": "Adapted from the Grand Comics Database", "source_url": source,
                    "license": "CC BY-SA 4.0", "license_url": receipt["metadata_license"],
                    "changes": "Fields normalised to Drop Rate's edition catalogue. Cover images excluded."}
        if (book.get("identity_status") in {"STRUCTURED", "VERIFIED"}
                and book.get("profile_status") in {"STRUCTURED", "VERIFIED"}
                and attributes.get("identity_source") == "OPEN_LIBRARY_CATALOGUE"
                and isinstance(receipt, dict) and receipt.get("provider") == "OPEN_LIBRARY"
                and receipt.get("version") == "book-bulk-v1"
                and receipt.get("metadata_license") == "https://openlibrary.org/developers/licensing"):
            import re
            source = attributes.get("source_url", "")
            if re.fullmatch(r"https://openlibrary[.]org/books/OL[1-9][0-9]*M", source):
                item["book_data_attribution"] = {
                    "text": "Edition metadata from Open Library", "source_url": source,
                    "license": "Open Library data licensing",
                    "license_url": receipt["metadata_license"],
                    "changes": "Factual edition metadata normalised; covers and market values excluded."}
        cover = book_cover_reference(book, item.get("language"))
        if cover and not (item.get("display_image_url") or item.get("image_url")):
            item["reference_image_path"] = "/api/v1/catalogue-browser/reference-image?" + urlencode({
                "provider": "Official Publisher", "system_code": details["system_code"],
                "language": item["language"], "provider_id": str(item["catalogue_id"]),
                "reference_kind": "book"})
            item["artwork_kind"] = "PUBLISHER_REFERENCE"
        # Covers never become approved inventory/Shopify media or proof of a copy.
    return items

