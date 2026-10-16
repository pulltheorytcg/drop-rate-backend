"""Exact book-printing comparisons for the already-connected UK sold feed.

Unknown printing/cover/condition never becomes a guessed value. No provider call,
price multiplier, scraping or AI price calculation belongs in this module.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .comic_identity import BOOK_CONDITIONS, BOOK_SYSTEMS
from .ebay_sold_pricing import _sold_at

PRINT_FIELDS = ("system_code","series_title","issue_number","volume_identifier","printing_number",
                "release_year","cover_code","cover_artist","barcode_gtin","publisher","book_format")
SPECIAL_STATE = r"\b(?:signed|signature|restored|restoration|qualified|incomplete|missing|detached|trimmed|married|repaired|purple|green label|yellow label)\b"


def printing_digest(book):
    return hashlib.sha256(json.dumps({k:book.get(k) for k in PRINT_FIELDS},sort_keys=True,separators=(',',':')).encode()).hexdigest()


async def attach_book_printings(connection, items, *, lock=False):
    books = [i for i in items if i.get("product_type") == "COMIC"]
    if not books: return items
    rows = await connection.fetch("""select b.*,pr.identity_status as profile_status
        from tcg.comic_printing_details b join tcg.catalogue_product_profiles pr on pr.catalogue_id=b.catalogue_id
        and pr.collectible_type='COMIC' and pr.system_code=b.system_code
        where b.catalogue_id=any($1::uuid[])""" + (" for share of b,pr" if lock else ""),
        list({i["catalogue_id"] for i in books}))
    by_id = {}
    for row in rows:
        book = dict(row)
        attributes = book.get("attributes") or {}
        if isinstance(attributes,str): attributes=json.loads(attributes)
        book.update(publisher=attributes.get("publisher"),book_format=attributes.get("book_format"))
        by_id[str(row["catalogue_id"])] = {k:book.get(k) for k in (*PRINT_FIELDS,"identity_status","profile_status")}
    for item in books:
        item["book_printing"] = by_id.get(str(item["catalogue_id"]),{})
        item["book_identity_digest"] = printing_digest(item["book_printing"])
    # Copy-specific exceptions must also constrain portfolio/list views whose
    # regular SELECT omits notes. These rows remain behind the caller's RLS.
    physical_ids = [i["id"] for i in books if i.get("id")]
    if physical_ids:
        notes = {str(r["id"]): r["notes"] for r in await connection.fetch(
            "select id,notes from tcg.inventory_items where id=any($1::uuid[])", physical_ids)}
        for item in books:
            if item.get("id"): item["notes"] = notes.get(str(item["id"]))
    return items


def eligibility(target):
    b = target.get("book_printing") or {}
    if b.get("identity_status") != "VERIFIED" or b.get("profile_status") != "VERIFIED":
        return "BOOK_PRINTING_REVIEW_REQUIRED"
    if b.get("system_code") not in BOOK_SYSTEMS or not all(b.get(k) for k in (
            "series_title","issue_number","publisher","release_year","printing_number","book_format")):
        return "EXACT_BOOK_PRINTING_REQUIRED"
    if b["book_format"] == "SINGLE_ISSUE" and not b.get("cover_code"):
        return "EXACT_BOOK_COVER_REQUIRED"
    if target.get("seal_status"):
        return "BOOK_PHYSICAL_REVIEW_REQUIRED"
    if re.search(SPECIAL_STATE, str(target.get("notes") or ""), re.I):
        return "SPECIAL_BOOK_STATE_REVIEW_REQUIRED"
    company,grade = target.get("grading_company"),target.get("grade")
    allowed = {"CGC","BGS"} if b["system_code"] == "MANGA" else {"CGC"}
    if company or grade:
        if (company not in allowed or not grade or target.get("condition")
                or not re.fullmatch(r"(?:10(?:\.0)?|[0-9](?:\.[0-9])?)",str(grade)) or Decimal(str(grade))<Decimal('.5')):
            return "BOOK_GRADE_REVIEW_REQUIRED"
    elif target.get("condition") not in BOOK_CONDITIONS:
        return "PHYSICAL_CONDITION_REQUIRED"
    return None


def query_for(target):
    b=target["book_printing"]
    return " ".join(str(x) for x in (b["series_title"],
        "Vol" if b["system_code"]=="MANGA" else "Issue",b["issue_number"],b["publisher"],b["release_year"],
        f"printing {b['printing_number']}",
        b.get("volume_identifier"),b.get("cover_code"),b.get("barcode_gtin"),target["language"],
        target.get("grading_company"),target.get("grade")) if x)


def _normal(value):
    return " ".join(re.sub(r"[^\w]+"," ",str(value or "").casefold()).split())


def _contains(text, value):
    clean=_normal(value)
    return bool(clean) and f" {clean} " in f" {_normal(text)} "


def exact_match(row, target):
    if eligibility(target): return False
    b=target["book_printing"]; title=str(row.get("title") or ""); text=_normal(title)
    if re.search(r"\b(?:bundle|lot|joblot|set of|collection of|choose|pick|poster|facsimile|replica|digital|kindle|ebook)\b",text) or re.search(SPECIAL_STATE,text):
        return False
    if re.search(r"\b\d+\s*(?:books|comics|volumes|issues|copies)\b|\bx\s*\d+\b|\b\d+\s*(?:-|–|to)\s*\d+\b",title,re.I):
        return False
    if not all(_contains(title,b[k]) for k in ("series_title","publisher","release_year")):
        return False
    if any(int(y)!=b["release_year"] for y in re.findall(r"\b((?:19|20|21)\d{2})\b",title)):
        return False
    # No title-name-only, absent-language or ISBN-only inference.
    if not _contains(title,target.get("language")): return False
    for language in ("English","Japanese","French","German","Chinese","Korean","Spanish","Italian","Portuguese"):
        if language!=target.get("language") and _contains(title,language): return False
    number=re.escape(str(b["issue_number"]))
    marker=r"(?:vol(?:ume)?\.?\s*|#\s*)" if b["system_code"]=="MANGA" else r"(?:issue\s*|#\s*)"
    if not re.search(marker+number+r"(?![\w.])",title,re.I): return False
    all_numbers=re.findall(r"(?:\bvol(?:ume)?\.?\s*|\bissue\s*|#\s*)(\d+(?:\.\d+)?)(?!\w)",title,re.I)
    if any(n != str(b["issue_number"]) for n in all_numbers): return False
    printing=str(b["printing_number"])
    words={"1":"first","2":"second","3":"third","4":"fourth","5":"fifth"}
    pword=words.get(printing,printing)
    if not re.search(rf"\b(?:{printing}(?:st|nd|rd|th)?|{pword})\s+(?:print|printing)\b|\bprinting\s+{printing}\b",title,re.I):
        return False
    other_prints=re.findall(r"\b(\d+)(?:st|nd|rd|th)?\s+(?:print|printing)\b|\bprinting\s+(\d+)\b",title,re.I)
    if any((a or c)!=printing for a,c in other_prints): return False
    if any(word!=pword and re.search(rf"\b{word}\s+print(?:ing)?\b",title,re.I) for word in words.values()): return False
    for field in ("volume_identifier","cover_code","cover_artist"):
        if b.get(field) and not _contains(title,b[field]): return False
    for marker in ("omnibus","deluxe","hardcover","virgin","foil","newsstand","variant","exclusive",
                   "annual","ashcan","preview","digest","3 in 1","library edition","collectors edition",
                   "collector edition","color edition","colour edition","anniversary edition"):
        if _contains(title,marker) and not any(_contains(b.get(k),marker) for k in ("series_title","issue_number","volume_identifier","cover_code","book_format")):
            return False
    if b["book_format"]=="HARDCOVER" and not _contains(title,"hardcover"): return False
    if b["book_format"]=="TRADE_PAPERBACK" and not (_contains(title,"paperback") or _contains(title,"tpb")): return False
    covers=re.findall(r"\bcover\s+([a-z])\b",title,re.I)
    if covers and any(not _contains(b.get("cover_code"),"Cover "+cover) for cover in covers): return False
    if b.get("barcode_gtin"):
        digits=re.sub(r"[\s-]","",str(b["barcode_gtin"]))
        if not re.search(r"(?<!\d)"+re.escape(digits)+r"(?!\d)",re.sub(r"[\s-]","",title)): return False
    company,grade=target.get("grading_company"),target.get("grade")
    if company:
        grades=re.findall(r"\b(CGC|BGS|CBCS|PSA|PGX)\s*(\d+(?:\.\d+)?)\b",title,re.I)
        if len(grades)!=1 or grades[0][0].upper()!=company or Decimal(grades[0][1])!=Decimal(str(grade)): return False
        if len(re.findall(r"\b(?:CGC|BGS|CBCS|PSA|PGX)\b",title,re.I))!=1: return False
        if re.search(r"\b(?:raw|ungraded|like|equivalent|potential|candidate)\b",text): return False
    else:
        if re.search(r"\b(?:cgc|bgs|cbcs|psa|pgx|graded|slab)\b",text): return False
        # Trawl's generic 'used' condition is not a book-grade comparison.
        condition=_normal(row.get("condition_raw"))
        if condition!=_normal(target["condition"]): return False
        # Longest-first avoids reading 'Mint' inside 'Near Mint'. Conflicting
        # title grades cannot be rescued by a generic provider condition.
        states=re.findall(r"\b(?:near mint|very fine|very good|mint|fine|good|fair|poor|nm|vf|vg)\b",text)
        aliases={"nm":"near mint","vf":"very fine","vg":"very good"}
        if any(aliases.get(state,state)!=condition for state in states): return False
    return True


def select_comps(payload, target, now):
    if payload.get("site")!="EBAY_GB" or payload.get("currency")!="GBP" or not isinstance(payload.get("results"),list):
        raise ValueError("UK GBP sold response required")
    rows=[r for r in payload["results"] if isinstance(r,dict)]
    counts=Counter(str(r.get("item_id")) for r in rows)
    comps=[]
    for row in rows:
        item_id=str(row.get("item_id") or "")
        sold=_sold_at(row.get("date_sold"))
        if (not item_id.isdigit() or counts[item_id]!=1 or row.get("currency") not in {"GBP","£"}
                or sold is None or not now-timedelta(days=90)<=sold<=now or not exact_match(row,target)):
            continue
        try:
            price=Decimal(str(row.get("sale_price")))
            shipping=None if row.get("shipping_price") is None else Decimal(str(row["shipping_price"]))
            if not price.is_finite() or not 0<price<Decimal('1e12') or (shipping is not None and (not shipping.is_finite() or not 0<=shipping<Decimal('1e12'))): continue
        except InvalidOperation: continue
        minor=lambda x:int((x*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        comps.append(dict(item_id=item_id,title=row["title"],sold_at=sold,price_minor=minor(price),
            shipping_minor=minor(shipping) if shipping is not None else None,
            condition_raw=row.get("condition_raw"),url=row.get("item_link")))
    return sorted(comps,key=lambda c:(c["sold_at"],c["item_id"]),reverse=True)[:5]
