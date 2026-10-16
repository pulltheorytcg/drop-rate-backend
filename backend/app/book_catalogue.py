"""Publisher edition facts for book browsing; never physical-copy approval."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from pydantic import ValidationError

from .comic_identity import ComicPrintingCreate


def publisher_page(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    paths = {"www.viz.com": "/manga-books/manga/", "www.dc.com": "/comics/",
             "www.marvel.com": "/comics/issue/"}
    prefix = paths.get(url.netloc)
    return value if (url.scheme == "https" and prefix and url.path.startswith(prefix)
                     and not url.query and not url.fragment) else None


async def with_book_details(connection, rows):
    """One bounded read; return book fields only, never private source metadata."""
    items = [dict(row) for row in rows]
    books = [row for row in items if row.get("product_type") == "COMIC" and row.get("catalogue_id")]
    if not books:
        return items
    records = await connection.fetch("""select b.*,pr.identity_status as profile_status
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
        if (book.get("identity_status") in {"STRUCTURED", "VERIFIED"}
                and book.get("profile_status") in {"STRUCTURED", "VERIFIED"}
                and attributes.get("identity_source") == "OFFICIAL_PUBLISHER_CATALOGUE"):
            source = publisher_page(attributes.get("source_url"))
            if source:
                item["publisher_source_url"] = source
                item["book_reference_scope"] = "PUBLISHER_EDITION"
        # Publisher cover links are provenance, not approved storefront media.
        # Existing canonical media gates continue to decide displayed artwork.
    return items
