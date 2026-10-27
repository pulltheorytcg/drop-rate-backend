"""Bounded, read-only eBay asking listings for an exact ISBN edition.

These are active seller offers, never sold evidence or a physical-copy value.
Provider I/O runs outside database transactions. Nothing is persisted.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .access_control import current_access_context
from .auth import AuthenticatedUser, require_user
from .book_openlibrary import canonical_isbn
from .db import user_connection
from .ebay_official_client import EbayApiError, EbayOfficialClient


router = APIRouter(prefix="/api/v1/catalogue-browser", tags=["catalogue-browser"])
ITEM_ID = re.compile(r"v1\|([1-9][0-9]{0,19})\|(0|[1-9][0-9]{0,19})")
SUCCESS_TTL = 3600
NEGATIVE_TTL = 300
BUSY_TTL = 5
MAX_ITEMS = 3
MAX_SUMMARIES = 50
MAX_LOOKUP_CALLS = 7
IDENTIFIER_FIELDS = ("gtin", "gtins", "isbn", "isbn10", "isbn13", "ean", "eans", "upc")
IDENTIFIER_ASPECTS = {"isbn", "isbn 10", "isbn 13", "isbn10", "isbn13", "ean", "ean 13", "gtin", "upc"}
LANGUAGES = {
    "english": "English", "en": "English", "eng": "English",
    "japanese": "Japanese", "ja": "Japanese", "jpn": "Japanese",
    "french": "French", "fr": "French", "german": "German", "de": "German",
    "spanish": "Spanish", "es": "Spanish", "italian": "Italian", "it": "Italian",
    "portuguese": "Portuguese", "pt": "Portuguese", "korean": "Korean", "ko": "Korean",
    "chinese": "Chinese", "zh": "Chinese",
}
UNSAFE_COPY = re.compile(
    r"\b(?:ebook|e book|kindle|digital|pdf|audiobook|audio book|poster|facsimile|replica|"
    r"bundle|joblot|job lot|box set|boxed set|set of|collection of|choose|pick|lot|"
    r"graded|slab|cgc|cbcs|bgs|psa|pgx|signed|signature|autographed|restored|restoration|"
    r"incomplete|missing|detached|trimmed|married|repaired|ex library|library copy|personalised|personalized)\b",
    re.I,
)
VOLUME_RE = re.compile(r"(?:\bvol(?:ume)?\.?\s*|\bissue\s*|#\s*)([0-9]+)(?![\w.])", re.I)


def _normal(value: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value or "").casefold()).split())


def normalize_isbn(value: object) -> str | None:
    try:
        return canonical_isbn(value)
    except (ValueError, TypeError):
        return None


def _isbn_aliases(isbn: str) -> list[str]:
    identifiers = [isbn]
    if isbn.startswith("978"):
        body = isbn[3:12]
        digit = (-sum(int(n) * (10-i) for i, n in enumerate(body))) % 11
        identifiers.append(body + ("X" if digit == 10 else str(digit)))
    return identifiers


def _isbn_query(isbn: str) -> str:
    """One documented keyword OR query built only from a valid canonical ISBN."""
    if not isinstance(isbn, str) or normalize_isbn(isbn) != isbn:
        raise ValueError("A canonical ISBN13 is required")
    identifiers = _isbn_aliases(isbn)
    return "(" + ",".join(identifiers) + ")" if len(identifiers) > 1 else isbn


def _object(value: object) -> dict:
    try:
        value = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _binding(value: object) -> str | None:
    value = _normal(value)
    if value in {"paperback", "paper back", "trade paperback", "softcover", "soft cover"}:
        return "Paperback"
    if value in {"hardcover", "hard cover", "hardback", "hard back"}:
        return "Hardcover"
    return None


def _binding_mentions(value: object) -> set[str]:
    text = _normal(value)
    result = set()
    if re.search(r"\b(?:paperback|paper back|softcover|soft cover|tpb)\b", text):
        result.add("Paperback")
    if re.search(r"\b(?:hardcover|hard cover|hardback|hard back)\b", text):
        result.add("Hardcover")
    return result


@dataclass(frozen=True)
class BookEdition:
    catalogue_id: str
    isbn: str
    title: str
    volume: str
    language: str
    binding: str | None
    publisher: str
    release_year: int | None
    digest: str

    def public_identity(self) -> dict:
        return {"title": self.title, "volume": self.volume, "language": self.language,
                "binding": self.binding}


def edition_target(row: dict) -> BookEdition | None:
    """Accept only a canonical imported edition, never client-supplied facts."""
    attrs = _object(row.get("attributes"))
    if (row.get("product_type") != "COMIC"
            or row.get("system_code") not in {"MANGA", "MARVEL_COMICS", "DC_COMICS", "OTHER_COMICS"}
            or row.get("identity_status") not in {"STRUCTURED", "VERIFIED"}
            or row.get("profile_status") not in {"STRUCTURED", "VERIFIED"}
            or attrs.get("identity_source") not in {"OPEN_LIBRARY_CATALOGUE", "OFFICIAL_PUBLISHER_CATALOGUE", "GCD_CATALOGUE"}
            or attrs.get("source_status") in {"REVOKED", "INACTIVE", "REJECTED"}):
        return None
    isbn = normalize_isbn(row.get("barcode_gtin"))
    title = row.get("series_title")
    volume = str(row.get("issue_number") or "")
    language = LANGUAGES.get(_normal(row.get("language")))
    publisher = attrs.get("publisher")
    book_format = attrs.get("book_format")
    if (not isbn or not isinstance(title, str) or not 1 <= len(title.strip()) <= 140
            or not re.fullmatch(r"(?:0|[1-9][0-9]{0,3})", volume) or not language
            or not isinstance(publisher, str) or not publisher.strip()
            or book_format not in {"MANGA", "TRADE_PAPERBACK", "HARDCOVER"}):
        return None
    declared_binding = _binding(row.get("volume_identifier"))
    binding = {"TRADE_PAPERBACK": "Paperback", "HARDCOVER": "Hardcover"}.get(book_format, declared_binding)
    if declared_binding and binding and declared_binding != binding:
        return None
    if UNSAFE_COPY.search(_normal(title)):
        return None
    # A reviewed metadata hold must not be cleared by finding a marketplace hit.
    from .book_openlibrary_bulk import reviewed_hold_registry, reviewed_identity_hold
    try:
        reviewed, _ = reviewed_hold_registry()
        receipt = _object(attrs.get("catalogue_import"))
        if reviewed_identity_hold(isbn=isbn, source_id=receipt.get("record_id"), reviewed=reviewed):
            return None
    except (ValueError, TypeError, KeyError, OSError):
        return None
    try:
        catalogue_id = str(UUID(str(row.get("catalogue_id"))))
    except (ValueError, TypeError):
        return None
    year = row.get("release_year")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1930 <= year <= 2200):
        return None
    # Include every canonical source/identity field, not just ISBN, so edits and
    # revocations cannot reuse a previous identity's cache entry.
    material = {key: row.get(key) for key in (
        "identity_key", "system_code", "series_title", "issue_number", "volume_identifier",
        "printing_number", "release_year", "cover_code", "cover_artist", "barcode_gtin",
        "identity_status", "profile_status", "profile_release_date", "language", "version")}
    material["attributes"] = attrs
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return BookEdition(catalogue_id, isbn, title.strip(), volume, language, binding, publisher.strip(), year, digest)


def _product(detail: dict) -> dict:
    product = detail.get("product", {})
    if not isinstance(product, dict):
        raise ValueError("INVALID_PRODUCT")
    return product


def _product_aspects(detail: dict) -> list[tuple[str, list[str]]]:
    """Read the documented PRODUCT aspectGroups shape without overwriting item facts."""
    groups = _product(detail).get("aspectGroups", [])
    if not isinstance(groups, list) or len(groups) > 20:
        raise ValueError("INVALID_PRODUCT_ASPECTS")
    result = []
    count = 0
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("INVALID_PRODUCT_ASPECTS")
        aspects = group.get("aspects")
        if not isinstance(aspects, list) or len(aspects) > 100:
            raise ValueError("INVALID_PRODUCT_ASPECTS")
        for aspect in aspects:
            if not isinstance(aspect, dict):
                raise ValueError("INVALID_PRODUCT_ASPECTS")
            name, values = aspect.get("localizedName"), aspect.get("localizedValues")
            if (not isinstance(name, str) or len(name) > 100
                    or not isinstance(values, list) or not values or len(values) > 30
                    or any(not isinstance(value, str) or len(value) > 500 for value in values)):
                raise ValueError("INVALID_PRODUCT_ASPECTS")
            count += len(values)
            if count > 100:
                raise ValueError("INVALID_PRODUCT_ASPECTS")
            result.append((_normal(name), values))
    return result


def _aspects(detail: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    rows = detail.get("localizedAspects", [])
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("INVALID_ASPECTS")
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("name"), str) or not isinstance(row.get("value"), str)
                or len(row["name"]) > 100 or len(row["value"]) > 500):
            raise ValueError("INVALID_ASPECTS")
        result.setdefault(_normal(row["name"]), []).append(row["value"])
    for name, values in _product_aspects(detail):
        result.setdefault(name, []).extend(values)
    if sum(len(values) for values in result.values()) > 100:
        raise ValueError("INVALID_ASPECTS")
    return result


def _additional_identifiers(detail: dict) -> dict[str, list[str]]:
    groups = _product(detail).get("additionalProductIdentities", [])
    if not isinstance(groups, list) or len(groups) > 10:
        raise ValueError("INVALID_PRODUCT_IDENTIFIERS")
    result = {}
    count = 0
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("productIdentity"), list):
            raise ValueError("INVALID_PRODUCT_IDENTIFIERS")
        rows = group["productIdentity"]
        count += len(rows)
        if count > 30:
            raise ValueError("INVALID_PRODUCT_IDENTIFIERS")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("INVALID_PRODUCT_IDENTIFIERS")
            name, value = row.get("identifierType"), row.get("identifierValue")
            if (not isinstance(name, str) or len(name) > 100
                    or not isinstance(value, str) or len(value) > 500):
                raise ValueError("INVALID_PRODUCT_IDENTIFIERS")
            name = _normal(name)
            if name in IDENTIFIER_ASPECTS:
                result.setdefault(name, []).append(value)
    return result


def _identifiers(detail: dict, aspects: dict[str, list[str]]) -> list[str]:
    values = []
    for obj in (detail, _product(detail)):
        for key in IDENTIFIER_FIELDS:
            if key not in obj:
                continue
            value = obj[key]
            values.extend(value if isinstance(value, list) else [value])
    for name, entries in aspects.items():
        if name in IDENTIFIER_ASPECTS:
            values.extend(entries)
    for entries in _additional_identifiers(detail).values():
        values.extend(entries)
    if len(values) > 30:
        raise ValueError("AMBIGUOUS_IDENTIFIERS")
    result = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("INVALID_IDENTIFIER")
        if _normal(value) in {"", "does not apply", "not applicable", "n a"}:
            continue
        # A field containing multiple conflicting IDs must not be treated as
        # one lucky search match. Equivalent ISBN10/13 pairs remain acceptable.
        for part in re.split(r"[,;/]", value):
            identifier = normalize_isbn(part)
            if identifier is None:
                raise ValueError("INVALID_IDENTIFIER")
            result.append(identifier)
    return result


def _mask_isbn(text: str, isbn: str) -> str:
    for identifier in _isbn_aliases(isbn):
        text = re.sub(r"(?<!\d)" + r"[\s-]*".join(re.escape(c) for c in identifier) + r"(?!\d)", "", text, flags=re.I)
    return text


def _money(value: object, *, allow_zero: bool = False) -> int | None:
    if not isinstance(value, dict) or value.get("currency") != "GBP" or isinstance(value.get("value"), bool):
        return None
    try:
        amount = Decimal(str(value.get("value")))
        if (not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0)
                or amount > 1_000_000 or amount * 100 != (amount * 100).to_integral_value()):
            return None
        return int(amount * 100)
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None


def _date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.utcoffset() is not None else None
    except (ValueError, TypeError):
        return None


def _listing_url(value: object, item_id: str) -> str | None:
    if not isinstance(value, str) or len(value) > 2000:
        return None
    match = ITEM_ID.fullmatch(item_id)
    try:
        url = urlsplit(value)
        if (not match or url.scheme != "https" or url.netloc not in {"www.ebay.co.uk", "ebay.co.uk", "www.ebay.com", "ebay.com"}
                or url.username or url.password or url.port or url.fragment):
            return None
        path = re.fullmatch(r"/itm/(?:[A-Za-z0-9_-]+/)?([0-9]+)/?", url.path)
        if not path or path[1] != match[1]:
            return None
        if match[2] != "0" and parse_qs(url.query).get("var") != [match[2]]:
            return None
        # Strip arbitrary tracking/redirect parameters only after the fixed
        # host, item path and exact returned item ID have all been checked.
        suffix = "?var=" + match[2] if match[2] != "0" else ""
        return "https://" + url.netloc + "/itm/" + match[1] + suffix
    except (ValueError, TypeError):
        return None


def _image_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 1000:
        return None
    try:
        url = urlsplit(value)
        if (url.scheme == "https" and url.netloc == "i.ebayimg.com" and not url.query and not url.fragment
                and not url.username and not url.password and not url.port
                and re.fullmatch(r"/images/g/[A-Za-z0-9_~=-]+/s-l[0-9]{2,4}\.(?:jpg|jpeg|png|webp)", url.path, re.I)):
            return value
    except (ValueError, TypeError):
        pass
    return None


def _availability_reason(detail: dict) -> str | None:
    estimated = detail.get("estimatedAvailabilities", [])
    if not isinstance(estimated, list) or len(estimated) > 20:
        return "INVALID_AVAILABILITY"
    for entry in [detail] + estimated:
        if not isinstance(entry, dict):
            return "INVALID_AVAILABILITY"
        for key in ("estimatedAvailabilityStatus", "availabilityStatus"):
            if key in entry:
                status = entry[key]
                if not isinstance(status, str) or status not in {"IN_STOCK", "LIMITED_STOCK"}:
                    return "UNAVAILABLE_ITEM"
        for key in ("estimatedAvailableQuantity", "estimatedRemainingQuantity", "availableQuantity", "quantityAvailable", "remainingQuantity"):
            if key in entry:
                quantity = entry[key]
                if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                    return "UNAVAILABLE_QUANTITY"
    return None


def _revision(detail: dict) -> str | None:
    value = detail.get("sellerItemRevision")
    if (isinstance(value, str) and 0 < len(value) <= 128 and value == value.strip()
            and value.isprintable()):
        return value
    return None


def _compact_detail(detail: dict, compact: dict, target: BookEdition, *, now: datetime,
                    expected_item_id: str) -> tuple[dict | None, str]:
    """Bind a separately returned GTIN to the same unchanged listing.

    No search fact or title supplies identity. Only a COMPACT GTIN from the
    identical item/revision can supplement an otherwise eligible PRODUCT read.
    """
    if not isinstance(compact, dict) or compact.get("itemId") != expected_item_id or detail.get("itemId") != expected_item_id:
        return None, "COMPACT_ITEM_ID_MISMATCH"
    revision = _revision(detail)
    if revision is None or _revision(compact) is None:
        return None, "COMPACT_REVISION_REQUIRED"
    if _revision(compact) != revision:
        return None, "COMPACT_REVISION_CHANGED"
    try:
        identifiers = _identifiers(compact, _aspects(compact))
    except ValueError:
        return None, "COMPACT_IDENTIFIER_INVALID"
    if normalize_isbn(compact.get("gtin")) != target.isbn or set(identifiers) != {target.isbn}:
        return None, "COMPACT_ISBN_MISSING_OR_CONFLICT"
    if _money(compact.get("price")) is None or _money(compact.get("price")) != _money(detail.get("price")):
        return None, "COMPACT_PRICE_CHANGED_OR_INVALID"
    availability_reason = _availability_reason(compact)
    if availability_reason:
        return None, "COMPACT_" + availability_reason
    availability = [compact] + compact.get("estimatedAvailabilities", [])
    if not any(any(key in entry for key in (
            "estimatedAvailabilityStatus", "availabilityStatus", "estimatedAvailableQuantity",
            "estimatedRemainingQuantity", "availableQuantity", "quantityAvailable", "remainingQuantity"))
            for entry in availability):
        return None, "COMPACT_AVAILABILITY_REQUIRED"
    if any(compact.get(key) is not None for key in ("currentBidPrice", "minimumPriceToBid")):
        return None, "COMPACT_AUCTION_STATE"
    for key in ("bidCount", "uniqueBidderCount"):
        if key in compact and (isinstance(compact[key], bool) or not isinstance(compact[key], int) or compact[key] != 0):
            return None, "COMPACT_AUCTION_STATE"
    if "itemWebUrl" in compact and _listing_url(compact["itemWebUrl"], expected_item_id) is None:
        return None, "COMPACT_ITEM_URL_CONFLICT"
    if "itemEndDate" in compact:
        end = _date(compact["itemEndDate"])
        if end is None or end <= now:
            return None, "COMPACT_ENDED_OR_INVALID_DATE"
        if "itemEndDate" in detail and end != _date(detail["itemEndDate"]):
            return None, "COMPACT_END_DATE_CHANGED"
    merged = copy.deepcopy(detail)
    # Every original PRODUCT conflict has already been checked. Do not replace
    # its title, condition, binding, language or other edition evidence.
    merged["gtin"] = compact["gtin"]
    merged["price"] = copy.deepcopy(compact["price"])
    merged["estimatedAvailabilities"] = copy.deepcopy(compact.get("estimatedAvailabilities", []))
    for key in ("estimatedAvailabilityStatus", "availabilityStatus", "estimatedAvailableQuantity",
                "estimatedRemainingQuantity", "availableQuantity", "quantityAvailable", "remainingQuantity", "itemEndDate"):
        if key in compact:
            merged[key] = copy.deepcopy(compact[key])
    return merged, "COMPACT_GTIN_SAME_REVISION"


def _summary_candidates(rows: list, target: BookEdition) -> tuple[list[str], list[dict]]:
    """Rank at most fifty discovery hints; none can establish a listing match."""
    candidates, summaries, seen = [], [], set()
    for index, row in enumerate(rows[:MAX_SUMMARIES]):
        if not isinstance(row, dict):
            continue
        item_id = row.get("itemId")
        if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id) or item_id in seen:
            continue
        seen.add(item_id)
        title = row.get("title") if isinstance(row.get("title"), str) else ""
        summaries.append({"item_id": item_id, "title": title[:250]})
        title = title if len(title) <= 500 else ""
        masked = _mask_isbn(title, target.isbn)
        normalized = _normal(masked)
        volumes = set(str(int(value)) for value in VOLUME_RE.findall(masked))
        bindings = _binding_mentions(masked)
        language_match = bool(re.search(r"\b" + target.language.casefold() + r"\b", normalized))
        year_conflict = bool(target.release_year and any(
            int(year) != target.release_year for year in re.findall(r"\b((?:19|20|21)\d{2})\b", masked)))
        bundle_conflict = bool(re.search(
            r"\b\d+\s*(?:books|comics|volumes|issues|copies)\b|\bx\s*\d+\b|\b\d+\s*[x×]\b|\b\d+\s*(?:-|–|to)\s*\d+\b"
            r"|(?:\bvol(?:ume)?s?\.?\s*|\bissues?\s*|#\s*)\d+\s*(?:&|and|\+|,|/)\s*(?:vol(?:ume)?s?\.?\s*)?\d+\b",
            masked, re.I))
        edition_conflict = any(marker in normalized and marker not in _normal(target.title) for marker in (
            "omnibus", "deluxe", "library edition", "collector edition", "collectors edition",
            "colour edition", "color edition", "anniversary edition", "variant", "exclusive"))
        conflict = bool(UNSAFE_COPY.search(normalized) or (volumes and volumes != {target.volume})
                        or len(bindings) > 1 or (target.binding and bindings - {target.binding})
                        or year_conflict or bundle_conflict or edition_conflict
                        or any(language != target.language and re.search(r"\b" + language.casefold() + r"\b", normalized)
                               for language in set(LANGUAGES.values())))
        # Complete edition hints are more useful than an ISBN pasted into an
        # otherwise vague title. All hints still require actual detail proof.
        score = (not conflict, set(_normal(target.title).split()).issubset(set(normalized.split())),
                 volumes == {target.volume}, len(bindings) == 1, language_match, masked != title)
        candidates.append((score, index, item_id))
    candidates.sort(key=lambda candidate: (candidate[0], -candidate[1]), reverse=True)
    return [candidate[2] for candidate in candidates], summaries


def _assess_listing(detail: dict, target: BookEdition, *, checked_at: datetime, expected_item_id: str) -> tuple[dict | None, str]:
    def reject(reason):
        return None, reason
    if not isinstance(detail, dict) or not ITEM_ID.fullmatch(expected_item_id) or detail.get("itemId") != expected_item_id:
        return reject("ITEM_ID_MISMATCH")
    title, condition = detail.get("title"), detail.get("condition")
    if not isinstance(title, str) or not title.strip() or len(title) > 500 or not isinstance(condition, str) or not condition.strip() or len(condition) > 200:
        return reject("MISSING_TITLE_OR_CONDITION")
    buying = detail.get("buyingOptions")
    if (not isinstance(buying, list) or len(buying) > 10 or not all(isinstance(v, str) for v in buying)
            or "FIXED_PRICE" not in buying or "AUCTION" in buying):
        return reject("FIXED_PRICE_REQUIRED")
    if _object(detail.get("itemLocation")).get("country") != "GB":
        return reject("UK_LISTING_REQUIRED")
    end = None
    if "itemEndDate" in detail:
        end = _date(detail["itemEndDate"])
        if end is None or end <= checked_at:
            return reject("ENDED_OR_INVALID_DATE")
    availability_reason = _availability_reason(detail)
    if availability_reason:
        return reject(availability_reason)
    price = _money(detail.get("price"))
    if price is None:
        return reject("INVALID_GBP_PRICE")
    url = _listing_url(detail.get("itemWebUrl"), expected_item_id)
    if url is None:
        return reject("INVALID_ITEM_URL")
    try:
        aspects = _aspects(detail)
        identifiers = _identifiers(detail, aspects)
    except ValueError as exc:
        return reject(str(exc))
    if identifiers and set(identifiers) != {target.isbn}:
        return reject("ISBN_MISSING_OR_CONFLICT")
    masked = _mask_isbn(title, target.isbn)
    normalized = _normal(masked)
    copy_text = normalized + " " + _normal(condition)
    if UNSAFE_COPY.search(copy_text):
        return reject("DIGITAL_BUNDLE_GRADE_OR_SPECIAL_COPY")
    if re.search(r"\b(?:dust ?jacket only|jacket only|cover only|empty box|no book|without (?:the )?book|without dust ?jacket)\b", copy_text):
        return reject("INCOMPLETE_BOOK_OR_ACCESSORY")
    if re.search(r"\b\d+\s*(?:books|comics|volumes|issues|copies)\b|\bx\s*\d+\b|\b\d+\s*[x×]\b|\b\d+\s*(?:-|–|to)\s*\d+\b", masked, re.I):
        return reject("MULTI_VOLUME_OR_RANGE")
    if re.search(r"(?:\bvol(?:ume)?s?\.?\s*|\bissues?\s*|#\s*)\d+\s*(?:&|and|\+|,|/)\s*\d+\b", masked, re.I):
        return reject("MULTI_VOLUME_OR_RANGE")
    # Once this ISBN and its ISBN10 equivalent are masked, another long ID is
    # conflicting evidence, not a second chance to match the search result.
    for candidate in re.findall(r"(?<!\w)(?:\d{9,}[\dX]|\d+(?:[- ]\d+){2,5})(?!\w)", masked, re.I):
        digits = re.sub(r"[- ]", "", candidate)
        if len(digits) >= 10:
            return reject("CONFLICTING_TITLE_IDENTIFIER")
    if re.search(r"\bISBN(?:[ -]?1[03])?[ :\s-]*[0-9][0-9X\s-]{8,}", masked, re.I):
        return reject("CONFLICTING_TITLE_IDENTIFIER")
    if not set(_normal(target.title).split()).issubset(set(normalized.split())):
        return reject("TITLE_MISMATCH")
    for key, values in aspects.items():
        if key in {"professional grader", "grading company", "certification", "certification number", "grade"}:
            if any(_normal(v) not in {"", "no", "none", "ungraded", "not professionally graded", "not applicable", "n a", "does not apply"} for v in values):
                return reject("GRADED_COPY_ASPECT")
        if key in {"signed", "autographed", "personalised", "personalized", "restored", "restoration", "graded", "ex library"}:
            if any(_normal(v) not in {"no", "false", "not signed", "unsigned", "not graded", "ungraded", "not applicable", "n a"} for v in values):
                return reject("SPECIAL_COPY_ASPECT")
        if any(UNSAFE_COPY.search(_normal(v)) for v in values if key in {"format", "book format", "binding", "type", "features", "special attributes"}):
            return reject("DIGITAL_BUNDLE_GRADE_OR_SPECIAL_COPY")
    language_values = aspects.get("language", [])
    if not language_values or any(LANGUAGES.get(_normal(v)) != target.language for v in language_values):
        return reject("LANGUAGE_MISSING_OR_CONFLICT")
    for language in set(LANGUAGES.values()):
        if language != target.language and re.search(r"\b" + language.casefold() + r"\b", normalized):
            return reject("CONFLICTING_TITLE_LANGUAGE")
    bindings = set()
    for key in ("format", "book format", "binding"):
        for value in aspects.get(key, []):
            explicit = _binding(value)
            if explicit:
                bindings.add(explicit)
            else:
                mentions = _binding_mentions(value)
                if mentions:
                    bindings.update(mentions)
                else:
                    return reject("PHYSICAL_BINDING_REQUIRED")
    if len(bindings) != 1:
        return reject("PHYSICAL_BINDING_REQUIRED")
    binding = next(iter(bindings))
    if (target.binding and binding != target.binding) or (_binding_mentions(masked) - {binding}):
        return reject("BINDING_CONFLICT")
    numbers = [str(int(v)) for v in VOLUME_RE.findall(masked)]
    for key in ("volume", "volume number", "issue", "issue number"):
        for value in aspects.get(key, []):
            value = re.sub(r"^(?:vol(?:ume)?\.?|issue|#)\s*", "", value.strip(), flags=re.I)
            if not re.fullmatch(r"[0-9]{1,4}", value):
                return reject("VOLUME_CONFLICT")
            numbers.append(str(int(value)))
    if not numbers or set(numbers) != {target.volume}:
        return reject("VOLUME_MISSING_OR_CONFLICT")
    for marker in ("omnibus", "deluxe", "library edition", "collector edition", "collectors edition", "colour edition", "color edition", "anniversary edition", "variant", "exclusive"):
        if marker in normalized and marker not in _normal(target.title):
            return reject("DIFFERENT_EDITION")
    for value in aspects.get("publisher", []):
        if re.sub(r"\W", "", value.casefold()) != re.sub(r"\W", "", target.publisher.casefold()):
            return reject("PUBLISHER_CONFLICT")
    for value in aspects.get("publication year", []):
        if target.release_year and str(target.release_year) != value.strip():
            return reject("PUBLICATION_YEAR_CONFLICT")
    if target.release_year and any(int(year) != target.release_year for year in re.findall(r"\b((?:19|20|21)\d{2})\b", masked)):
        return reject("PUBLICATION_YEAR_CONFLICT")
    listed = _date(detail.get("itemCreationDate"))
    if "itemCreationDate" in detail and (listed is None or listed > checked_at + timedelta(minutes=5)):
        return reject("INVALID_LISTING_DATE")
    # Missing identity is reported only after every other gate passes, so a
    # COMPACT identity read cannot be spent rescuing an otherwise unsafe item.
    if not identifiers:
        return reject("ISBN_MISSING_OR_CONFLICT")
    shipping_values = []
    shipping = detail.get("shippingOptions", [])
    if isinstance(shipping, list):
        for option in shipping[:20]:
            if isinstance(option, dict):
                amount = _money(option.get("shippingCost"), allow_zero=True)
                if amount is not None:
                    shipping_values.append(amount)
    item = {"item_id": expected_item_id, "title": title, "condition": condition,
            "binding": binding, "price_minor": price,
            "shipping_minor": min(shipping_values) if shipping_values else None,
            "url": url, "image_url": _image_url(_object(detail.get("image")).get("imageUrl")),
            "listed_at": listed.isoformat() if listed else None, "ends_at": end.isoformat() if end else None,
            "checked_at": checked_at.isoformat()}
    return item, "MATCHED"


def listing_reference(detail: dict, target: BookEdition, *, checked_at: datetime, expected_item_id: str) -> dict | None:
    return _assess_listing(detail, target, checked_at=checked_at, expected_item_id=expected_item_id)[0]


def _empty(target: BookEdition | None, *, status: str, reason: str, now: datetime, ttl: int = NEGATIVE_TTL, catalogue_id: str | None = None) -> dict:
    return {"status": status, "reason": reason, "scope": "EDITION_ACTIVE_LISTINGS",
            "source": "EBAY_BROWSE", "observation_type": "ACTIVE", "currency": "GBP",
            "physical_valuation_eligible": False, "catalogue_id": target.catalogue_id if target else catalogue_id,
            "isbn": target.isbn if target else None, "edition_digest": target.digest if target else None,
            "edition": target.public_identity() if target else None,
            "checked_at": now.isoformat(), "expires_at": (now + timedelta(seconds=ttl)).isoformat(),
            "item_count": 0, "asking_low_minor": None, "asking_high_minor": None, "items": []}


class ContextUnavailable(RuntimeError):
    pass


@dataclass
class _LookupBudget:
    """Conservative request slots for this lookup, independent of other owners."""
    limit: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.used += 1
        return True


class BookListingContextService:
    """One process-wide client, budget, semaphore, LRU and in-flight registry."""

    def __init__(self, client: EbayOfficialClient | None, *, daily_call_limit: int = 500,
                 cache_size: int = 256, max_concurrent: int = 2, max_inflight: int = 32,
                 monotonic=time.monotonic, utcnow=None):
        self.client = client
        self.daily_call_limit = max(0, min(int(daily_call_limit), 4000))
        self.cache_size = min(max(1, cache_size), 512)
        self.max_inflight = max_inflight
        self.monotonic = monotonic
        self.utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self.lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self.inflight: dict[str, asyncio.Task] = {}
        self.budget_day = self.utcnow().date()
        self.calls_used = 0
        self.blocked_until = 0.0
        self.block_reason = "PROVIDER_BACKOFF"
        if client is not None:
            client._before_browse_request = self.reserve_call

    async def reserve_call(self):
        async with self.lock:
            if self.monotonic() < self.blocked_until:
                raise ContextUnavailable(self.block_reason)
            day = self.utcnow().date()
            if day > self.budget_day:
                self.budget_day, self.calls_used = day, 0
            if self.calls_used >= self.daily_call_limit:
                raise ContextUnavailable("DAILY_CALL_LIMIT")
            self.calls_used += 1

    async def _provider_failure(self, error: EbayApiError):
        status = error.status_code
        delay = 86400 if status in {401, 403} else max(NEGATIVE_TTL, min(86400, int(error.retry_after_seconds or 3600))) if status == 429 else NEGATIVE_TTL
        reason = "PROVIDER_ACCESS_REQUIRED" if status in {401, 403} else "PROVIDER_RATE_LIMIT" if status == 429 else "PROVIDER_UNAVAILABLE"
        async with self.lock:
            self.blocked_until = max(self.blocked_until, self.monotonic() + delay)
            self.block_reason = reason
        return reason

    async def get(self, target: BookEdition, *, diagnostics: bool = False) -> dict:
        key = target.digest
        async with self.lock:
            cached = self.cache.get(key)
            if cached and cached[0] > self.monotonic():
                self.cache.move_to_end(key)
                result = copy.deepcopy(cached[1])
                result["catalogue_id"] = target.catalogue_id
                if not diagnostics:
                    result.pop("diagnostics", None)
                return result
            if cached:
                del self.cache[key]
            task = self.inflight.get(key)
            if task is None:
                if len(self.inflight) >= self.max_inflight:
                    return _empty(target, status="UNAVAILABLE", reason="BUSY", now=self.utcnow(), ttl=BUSY_TTL)
                task = asyncio.create_task(self._run(target))
                self.inflight[key] = task
        # A navigation cancellation must not cancel the one shared provider
        # operation and force every other owner to issue the same requests.
        result = copy.deepcopy(await asyncio.shield(task))
        result["catalogue_id"] = target.catalogue_id
        if not diagnostics:
            result.pop("diagnostics", None)
        return result

    async def probe_listing(self, target: BookEdition, item_id: str) -> dict:
        """Internal opt-in probe only; the HTTP route never accepts listing IDs.

        The CLI enforces its tiny public fixture allowlist. This shares normal
        admission, budget and validation, but cannot seed the discovery cache.
        """
        if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id):
            raise ValueError("Invalid pinned item ID")
        return copy.deepcopy(await self._run(target, pinned_item_id=item_id))

    async def _read_candidate(self, target: BookEdition, item_id: str, diagnostic: dict,
                              budget: _LookupBudget) -> dict | None:
        if not budget.take():
            diagnostic["lookup_limit_reached"] = True
            return None
        try:
            detail = await self.client.get_item(item_id)
        except EbayApiError as exc:
            if exc.status_code != 404:
                raise
            diagnostic["detail_count"] += 1
            diagnostic["candidates"].append({"item_id": item_id, "reason": "ITEM_NO_LONGER_AVAILABLE"})
            return None
        diagnostic["detail_count"] += 1
        item, reason = _assess_listing(detail, target, checked_at=self.utcnow(), expected_item_id=item_id)
        candidate = _diagnostic(detail, item_id, reason)
        diagnostic["candidates"].append(candidate)
        if item or reason != "ISBN_MISSING_OR_CONFLICT":
            return item
        # A conflicting identifier never gets another chance through COMPACT.
        if _identifiers(detail, _aspects(detail)):
            return None
        if _revision(detail) is None:
            candidate["compact_identity"] = {"requested": False, "reason": "PRODUCT_REVISION_REQUIRED"}
            return None
        if not budget.take():
            candidate["compact_identity"] = {"requested": False, "reason": "LOOKUP_CALL_LIMIT"}
            diagnostic["lookup_limit_reached"] = True
            return None
        diagnostic["compact_count"] += 1
        try:
            compact = await self.client.get_item(item_id, fieldgroups="COMPACT")
        except EbayApiError as exc:
            if exc.status_code != 404:
                raise
            candidate["reason"] = "COMPACT_ITEM_NO_LONGER_AVAILABLE"
            candidate["compact_identity"] = {"requested": True, "reason": "COMPACT_ITEM_NO_LONGER_AVAILABLE"}
            return None
        merged, proof_reason = _compact_detail(detail, compact, target, now=self.utcnow(), expected_item_id=item_id)
        candidate["compact_identity"] = _compact_diagnostic(detail, compact, proof_reason)
        if merged is None:
            candidate["reason"] = proof_reason
            return None
        item, reason = _assess_listing(merged, target, checked_at=self.utcnow(), expected_item_id=item_id)
        candidate["reason"] = reason
        if item:
            candidate["identity_evidence"] = "COMPACT_GTIN_SAME_REVISION"
        return item

    async def _run(self, target: BookEdition, *, pinned_item_id: str | None = None) -> dict:
        now = self.utcnow()
        result = _empty(target, status="UNAVAILABLE", reason="NO_EXACT_ACTIVE_LISTINGS", now=now)
        diagnostic = {"search_count": 0, "candidate_count": 0, "detail_count": 0,
                      "compact_count": 0, "search_summaries": [], "candidates": [], "lookup_limit_reached": False}
        budget = _LookupBudget(MAX_LOOKUP_CALLS if pinned_item_id is None else 2)
        acquired = False
        try:
            if self.client is None:
                result["status"], result["reason"] = "DISABLED", "CREDENTIALS_REQUIRED"
            else:
                try:
                    await asyncio.wait_for(self.semaphore.acquire(), timeout=3)
                except (TimeoutError, asyncio.TimeoutError):
                    # Local queue contention is not a failed provider request;
                    # it must not stop healthy requests already holding slots.
                    raise ContextUnavailable("BUSY") from None
                acquired = True
                if self.monotonic() < self.blocked_until:
                    raise ContextUnavailable(self.block_reason)
                async with asyncio.timeout(45):
                    if pinned_item_id is None:
                        budget.take()
                        payload = await self.client.search_items(query=_isbn_query(target.isbn), limit=MAX_SUMMARIES,
                            item_location_country="GB", fixed_price_only=True)
                        diagnostic["search_count"] = 1
                        diagnostic["search_mode"] = "ISBN_KEYWORD_OR"
                        rows = payload.get("itemSummaries", [])
                        if not isinstance(rows, list):
                            raise ValueError("INVALID_SEARCH_SHAPE")
                        diagnostic["candidate_count"] = min(len(rows), MAX_SUMMARIES)
                        candidates, diagnostic["search_summaries"] = _summary_candidates(rows, target)
                    else:
                        candidates = [pinned_item_id]
                        diagnostic["candidate_count"] = 1
                    items = []
                    for item_id in candidates:
                        if budget.remaining <= 0:
                            diagnostic["lookup_limit_reached"] = True
                            break
                        item = await self._read_candidate(target, item_id, diagnostic, budget)
                        if item:
                            items.append(item)
                            if len(items) == MAX_ITEMS:
                                break
                    items = [item for item in items if not item["ends_at"] or _date(item["ends_at"]) > self.utcnow()]
                    if items:
                        expires = min([now + timedelta(seconds=SUCCESS_TTL)] +
                                      [_date(item["ends_at"]) for item in items if item["ends_at"]])
                        result.update(status="AVAILABLE", reason="EXACT_ISBN_ACTIVE_LISTINGS", item_count=len(items), items=items,
                                      asking_low_minor=min(item["price_minor"] for item in items),
                                      asking_high_minor=max(item["price_minor"] for item in items),
                                      expires_at=expires.isoformat())
        except EbayApiError as exc:
            result["reason"] = await self._provider_failure(exc)
            diagnostic["provider_status_code"] = exc.status_code
        except ContextUnavailable as exc:
            result["reason"] = str(exc)
            if result["reason"] == "BUSY":
                result["expires_at"] = (self.utcnow() + timedelta(seconds=BUSY_TTL)).isoformat()
        except (TimeoutError, asyncio.TimeoutError):
            result["reason"] = await self._provider_failure(EbayApiError("Provider timeout", retryable=True))
        except (ValueError, TypeError, KeyError, InvalidOperation):
            result["reason"] = "PROVIDER_DATA_INVALID"
        except Exception:
            # Never expose a provider body, token, URL or arbitrary exception.
            result["reason"] = "PROVIDER_UNAVAILABLE"
        finally:
            if acquired:
                self.semaphore.release()
            diagnostic["lookup_call_limit"] = budget.limit
            diagnostic["lookup_call_slots_used"] = budget.used
            result["diagnostics"] = diagnostic
            ttl = max(0.0, (_date(result["expires_at"]) - self.utcnow()).total_seconds())
            if pinned_item_id is None:
                async with self.lock:
                    self.inflight.pop(target.digest, None)
                    self.cache[target.digest] = (self.monotonic() + ttl, result)
                    self.cache.move_to_end(target.digest)
                    while len(self.cache) > self.cache_size:
                        self.cache.popitem(last=False)
        return result


def _diagnostic(detail: dict, item_id: str, reason: str) -> dict:
    """Allowlisted discovery facts only; no raw bodies or access credentials."""
    if not isinstance(detail, dict):
        return {"item_id": item_id, "reason": reason}
    try:
        aspects = _aspects(detail)
    except ValueError:
        aspects = {}
    safe = {"item_id": item_id, "reason": reason,
            "title": str(detail.get("title") or "")[:250],
            "currency": str(_object(detail.get("price")).get("currency") or "")[:8],
            "language": aspects.get("language", [])[:3],
            "binding": (aspects.get("format", []) + aspects.get("book format", []) + aspects.get("binding", []))[:3],
            "volume": (aspects.get("volume", []) + aspects.get("volume number", []) + aspects.get("issue number", []))[:3],
            "publisher": aspects.get("publisher", [])[:3],
            "publication_year": aspects.get("publication year", [])[:3],
            "seller_item_revision": _revision(detail),
            "product_present": isinstance(detail.get("product"), dict),
            "availability": []}
    estimated = detail.get("estimatedAvailabilities", [])
    for entry in [detail] + (estimated[:3] if isinstance(estimated, list) else []):
        if isinstance(entry, dict):
            for key in ("estimatedAvailabilityStatus", "availabilityStatus"):
                if key in entry:
                    safe["availability"].append(str(entry[key])[:80] if isinstance(entry[key], str) else "INVALID_STATUS_SHAPE")
    try:
        safe["identifiers"] = _identifiers(detail, aspects)[:10]
    except ValueError:
        safe["identifiers"] = ["INVALID_OR_AMBIGUOUS"]
    # Keep a bounded view of public identifier fields when normalization
    # rejects a mixed ISBN/UPC response. Matching remains fail-closed.
    safe["raw_identifiers"] = {}
    for prefix, obj in (("item", detail), ("product", _object(detail.get("product")))):
        for key in IDENTIFIER_FIELDS:
            value = obj.get(key)
            values = value if isinstance(value, list) else [value]
            strings = [value[:80] for value in values[:3] if isinstance(value, str)]
            if strings:
                safe["raw_identifiers"][f"{prefix}.{key}"] = strings
    for name in sorted(IDENTIFIER_ASPECTS):
        values = aspects.get(name, [])
        if values:
            safe["raw_identifiers"][f"aspects.{name}"] = [value[:80] for value in values[:3]]
    try:
        for name, values in _additional_identifiers(detail).items():
            safe["raw_identifiers"][f"product.additionalProductIdentities.{name}"] = [value[:80] for value in values[:3]]
    except ValueError:
        safe["product_identifier_shape"] = "INVALID"
    safe["product_aspects"] = {}
    try:
        for name, values in _product_aspects(detail):
            if name in IDENTIFIER_ASPECTS | {"language", "format", "book format", "binding", "volume", "volume number", "issue number", "publisher", "publication year"}:
                current = safe["product_aspects"].setdefault(name, [])
                current.extend(value[:80] for value in values[:max(0, 3-len(current))])
    except ValueError:
        safe["product_aspect_shape"] = "INVALID"
    return safe


def _compact_diagnostic(detail: dict, compact: dict, reason: str) -> dict:
    if not isinstance(compact, dict):
        return {"requested": True, "reason": reason, "shape": "INVALID"}
    revision, compact_revision = _revision(detail), _revision(compact)
    item_id = compact.get("itemId")
    safe = {"requested": True, "reason": reason,
            "item_id": item_id if isinstance(item_id, str) and ITEM_ID.fullmatch(item_id) else "INVALID",
            "product_revision": revision, "compact_revision": compact_revision,
            "revision_matched": revision is not None and revision == compact_revision,
            "gtin": compact["gtin"][:80] if isinstance(compact.get("gtin"), str) else None,
            "price_currency": str(_object(compact.get("price")).get("currency") or "")[:8],
            "price_minor": _money(compact.get("price")),
            "availability": _diagnostic(compact, item_id or "", reason).get("availability", [])}
    if "itemEndDate" in compact:
        end = _date(compact["itemEndDate"])
        safe["ends_at"] = end.isoformat() if end else "INVALID_DATE"
    return safe


def service_from_settings(settings) -> BookListingContextService:
    service = BookListingContextService(None, daily_call_limit=getattr(settings, "book_ebay_context_daily_call_limit", 500))
    if settings.ebay_client_id and settings.ebay_client_secret and settings.ebay_marketplace_id == "EBAY_GB":
        service.client = EbayOfficialClient(client_id=settings.ebay_client_id,
            client_secret=settings.ebay_client_secret, marketplace_id="EBAY_GB", timeout_seconds=8,
            before_browse_request=service.reserve_call)
    return service


TARGET_SQL = """select b.*,p.product_type,p.language,p.identity_key,
    pr.identity_status as profile_status,pr.release_date as profile_release_date
  from tcg.catalogue_products p
  join tcg.comic_printing_details b on b.catalogue_id=p.id
  join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
    and pr.system_code=b.system_code and pr.collectible_type='COMIC'
  where p.id=$1 and p.product_type='COMIC'
    and (pr.release_date<=current_date or
      (pr.release_date is null and b.release_year<extract(year from current_date)))"""


@router.get("/books/{catalogue_id}/listing-context")
async def book_listing_context(catalogue_id: UUID, request: Request,
                               user: Annotated[AuthenticatedUser, Depends(require_user)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id,
                               readonly_snapshot=True) as connection:
        await current_access_context(connection)
        row = await connection.fetchrow(TARGET_SQL, catalogue_id)
    if row is None:
        raise HTTPException(404, "Book edition unavailable")
    target = edition_target(dict(row))
    settings = request.app.state.settings
    now = datetime.now(timezone.utc)
    if not getattr(settings, "book_ebay_context_enabled", False):
        result = _empty(target, status="DISABLED", reason="FEATURE_DISABLED", now=now, catalogue_id=str(catalogue_id))
    elif target is None:
        result = _empty(None, status="UNAVAILABLE", reason="EXACT_EDITION_REQUIRED", now=now, catalogue_id=str(catalogue_id))
    else:
        service = getattr(request.app.state, "book_ebay_context_service", None)
        if service is None:
            service = service_from_settings(settings)
            request.app.state.book_ebay_context_service = service
        result = await service.get(target)
        # Identity/access can change while provider I/O runs. Recheck in a new
        # short transaction, never holding the first one open across the call.
        async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id,
                                   readonly_snapshot=True) as connection:
            await current_access_context(connection)
            current = await connection.fetchrow(TARGET_SQL, catalogue_id)
        latest = edition_target(dict(current)) if current else None
        if latest is None or latest.digest != target.digest:
            result = _empty(latest, status="UNAVAILABLE", reason="EDITION_CHANGED", now=datetime.now(timezone.utc), catalogue_id=str(catalogue_id))
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
