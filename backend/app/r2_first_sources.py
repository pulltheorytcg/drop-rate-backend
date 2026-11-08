"""Opt-in, metadata-only adapters for the separate R2-first reference catalogue.

These functions do not connect to PostgreSQL or object storage, approve an
identity, fetch artwork, publish inventory, or calculate a price. All output is
unreviewed source evidence. In particular, YGOPRODeck's passcodes and sets do not
resolve edition or assign its separate artwork array to individual printings.

Provider evidence reviewed on 2026-11-03:
* https://ygoprodeck.com/api-guide/ documents bulk/local caching and a 20/s
  ceiling. That is provider-access permission, not a Konami artwork licence.
* https://github.com/LorcanaJSON/LorcanaJSON-website/blob/main/index.html
  documents bulk files/metadata polling. Its generator's MIT licence is NOT a
  commercial licence to Disney/Ravensburger content. Dataset rights need review.
* https://github.com/scryfall/api-types describes the printing fields below;
  https://scryfall.com/docs/faqs/i-m-having-trouble-accessing-the-scryfall-api-or-i-m-blocked-17
  recommends bulk/local processing. Current full usage terms at
  https://scryfall.com/docs/api must be reviewed before enabling this importer.
* https://riftcodex.com/docs/ documents public reads, but bulk redistribution
  permission is unverified. Its downloader is deliberately deferred.

``approved_sources`` must come from the caller's reviewed provider registry;
it is not a user-input bypass or evidence that third-party rights were granted.
The separately reviewed Lorcast, MTGJSON and Card Collector Capital adapters
also expose factual metadata only. Their attribution/coverage notices ship in
catalogue-source-notices.txt. REVIEW_REQUIRED descriptors remain preparatory,
not permission to enable a job; in particular Riot approval is still required.
"""
from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from types import MappingProxyType
import unicodedata
from urllib.parse import urlsplit
from uuid import UUID

import httpx


MAX_SOURCE_BYTES = 64_000_000
MAX_SOURCE_ROWS = 200_000
MAX_NORMALIZED_ROWS = 300_000
TOTAL_DOWNLOAD_TIMEOUT_SECONDS = 60
SOURCE_REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0, pool=5.0)
NORMALIZED_FIELDS = frozenset({
    "provider", "system_code", "language", "provider_id", "product_type",
    "name", "set_id", "set_name", "card_number", "rarity", "finish",
    "release_date", "source_url",
})

_LANGUAGES = MappingProxyType({
    "en": "English", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "es": "Spanish", "ja": "Japanese", "ko": "Korean",
    "ru": "Russian", "zhs": "Simplified Chinese", "zht": "Traditional Chinese",
})
_LORCANA_LANGUAGES = frozenset({"en", "fr", "de", "it"})
_PUBLIC_HEADERS = {
    "User-Agent": "DropRateMetadataImport/1.0 (+https://app.droprate.co.uk)",
    "Accept": "application/json",
    "Accept-Encoding": "identity",
}


class SourceError(ValueError):
    """A bounded source read or deterministic normalization failed closed."""


class SourcePermissionError(SourceError):
    """No reviewed provider-access approval was supplied by the caller."""


class DeferredSourceError(SourceError):
    """This source is intentionally not available for a network import."""


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    provider: str
    system_code: str
    source_url: str
    source_revision: str
    permission_ref: str
    permission_status: str
    download_url: str | None
    max_bytes: int = MAX_SOURCE_BYTES
    catalogue_language: str = "English"


@dataclass(frozen=True, slots=True)
class FetchedSource:
    provider: str
    system_code: str
    source_url: str
    source_revision: str
    source_sha256: str
    records: list[dict]

    @property
    def record_count(self) -> int:
        return len(self.records)


def _language(language: str) -> tuple[str, str]:
    if not isinstance(language, str):
        raise SourceError("A supported language must be explicit")
    for code, name in _LANGUAGES.items():
        if language.casefold() in {code, name.casefold()}:
            return code, name
    raise SourceError("Unsupported language")


def source_descriptor(source: str, language: str = "English") -> SourceDescriptor:
    """Return fixed provider locators; never accept an arbitrary download URL."""
    if source == "reviewed_figures":
        if language not in {"English", "Not applicable"}:
            raise SourceError("Figure references do not establish a physical language")
        url = "https://github.com/pulltheorytcg/drop-rate-backend/blob/main/backend/data/r2_figure_starter_20261104.json"
        return SourceDescriptor(source, "FIGURES", url, "reviewed-figures-2026-11-04-metadata-v1",
            "https://github.com/pulltheorytcg/drop-rate-backend/blob/main/docs/R2_CATALOGUE_EXPANSION_20261104.md",
            "METADATA_ACCESS_DOCUMENTED", url, 131_072, catalogue_language="Not applicable")
    code, _ = _language(language)
    if source == "ygoprodeck":
        # Translated names in a localized API do not establish printing language.
        if code != "en":
            raise SourceError("YGOPRODeck printing-language support is English-only")
        url = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
        return SourceDescriptor(source, "YUGIOH", url, "api-v7-metadata-v1",
            "https://ygoprodeck.com/api-guide/", "METADATA_ACCESS_DOCUMENTED", url)
    if source == "lorcast":
        if code != "en":
            raise SourceError("Lorcast catalogue import supports English-only")
        url = "https://api.lorcast.com/v0/sets"
        return SourceDescriptor(source, "DISNEY_LORCANA", url, "api-v0-metadata-v1",
            "https://lorcast.com/docs/api", "METADATA_ACCESS_DOCUMENTED", url)
    if source == "mtgjson":
        if code != "en":
            raise SourceError("MTGJSON catalogue import supports English-only")
        url = "https://mtgjson.com/api/v5/AllPrintings.json.xz"
        return SourceDescriptor(source, "MAGIC_THE_GATHERING", url, "all-printings-v5-metadata-v2-mcm-id",
            "https://mtgjson.com/license/", "METADATA_ACCESS_DOCUMENTED", url, 128_000_000)
    if source == "cardcollectorcapital":
        if code != "en":
            raise SourceError("Sports checklist import supports English-only")
        url = "https://cardcollectorcapital.com/data/bowman-checklist-lookup-2026-10-27.json"
        return SourceDescriptor(source, "SPORTS_CARDS", url, "bowman-checklist-2026-10-27-metadata-v1",
            "https://cardcollectorcapital.com/data", "METADATA_ACCESS_DOCUMENTED", url, 2_000_000)
    if source == "cardcollectorcapital_heritage":
        if code != "en":
            raise SourceError("Heritage checklist import supports English-only")
        url = "https://cardcollectorcapital.com/data/2026-topps-heritage-short-prints.json"
        return SourceDescriptor(source, "SPORTS_CARDS", url,
            "topps-heritage-short-prints-2026-09-30-metadata-v1",
            "https://cardcollectorcapital.com/data", "METADATA_ACCESS_DOCUMENTED", url, 65_536)
    if source == "lorcanajson":
        if code not in _LORCANA_LANGUAGES:
            raise SourceError("Unsupported LorcanaJSON language")
        url = f"https://lorcanajson.org/files/current/{code}/allCards.json"
        return SourceDescriptor(source, "DISNEY_LORCANA", url, "format-v2-metadata-v1",
            "https://github.com/LorcanaJSON/LorcanaJSON-website/blob/main/index.html",
            "REVIEW_REQUIRED", url)
    if source == "scryfall":
        # Default Cards is not an all-language export. Other language payloads
        # may be normalized offline, but are not silently fetched from this file.
        if code != "en":
            raise SourceError("Scryfall bulk downloader supports English-only")
        url = "https://api.scryfall.com/bulk-data/default_cards"
        return SourceDescriptor(source, "MAGIC_THE_GATHERING", url,
            "default-cards-metadata-v1", "https://scryfall.com/docs/api",
            "REVIEW_REQUIRED", url)
    if source == "riftcodex":
        return SourceDescriptor(source, "RIFTBOUND", "https://riftcodex.com/docs/",
            "deferred-v0.2.0", "https://riftcodex.com/faq/", "DEFERRED", None)
    raise SourceError("Unknown catalogue source")


def _text(value, field: str, *, optional: bool = False, max_length: int = 512) -> str:
    if optional and value is None:
        return ""
    if not isinstance(value, str):
        raise SourceError(f"Invalid {field}")
    result = unicodedata.normalize("NFC", value).strip()
    if len(result) > max_length or any(unicodedata.category(c) == "Cc" for c in result):
        raise SourceError(f"Invalid {field}")
    if not result and not optional:
        raise SourceError(f"Missing {field}")
    return result


def _nullable_text(value, field: str) -> str | None:
    return _text(value, field, optional=True, max_length=160) or None


def _date(value) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise SourceError("Invalid release date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SourceError("Invalid release date") from exc
    return value


def _numeric_id(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SourceError("Invalid provider identifier")
    raw = str(value)
    if not re.fullmatch(r"[0-9]{1,12}", raw) or int(raw) < 1:
        raise SourceError("Invalid provider identifier")
    return str(int(raw))


def _provider_id(provider: str, *parts) -> str:
    # A JSON tuple avoids ambiguous delimiter concatenation in source IDs.
    canonical = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return provider + ":" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rows(value, field: str) -> list[Mapping]:
    if not isinstance(value, list) or not value or len(value) > MAX_SOURCE_ROWS:
        raise SourceError(f"Invalid or empty {field} snapshot")
    if any(not isinstance(row, Mapping) for row in value):
        raise SourceError(f"Invalid {field} row")
    return value


def _record(provider: str, system: str, language: str, provider_id: str,
            *, name, set_id="", set_name="", card_number="", rarity=None,
            finish=None, release_date=None, source_url: str) -> dict:
    return {
        "provider": provider, "system_code": system, "language": language,
        "provider_id": provider_id, "product_type": "CARD",
        "name": _text(name, "card name"),
        "set_id": _text(set_id, "set identifier", optional=True, max_length=160),
        "set_name": _text(set_name, "set name", optional=True),
        "card_number": _text(card_number, "card number", optional=True, max_length=160),
        "rarity": _nullable_text(rarity, "rarity"),
        "finish": _nullable_text(finish, "finish"),
        "release_date": _date(release_date), "source_url": source_url,
    }


def _deduplicate(records: list[dict]) -> list[dict]:
    if not records or len(records) > MAX_NORMALIZED_ROWS:
        raise SourceError("Empty or oversized normalized snapshot")
    by_key = {}
    for record in records:
        key = (record["provider"], record["provider_id"], record["language"])
        previous = by_key.get(key)
        if previous is not None and previous != record:
            raise SourceError("Conflicting duplicate provider identity")
        by_key[key] = record
    return [by_key[key] for key in sorted(by_key)]


def normalize_ygoprodeck(payload, language: str = "English") -> list[dict]:
    """Preserve passcode/set/rarity; never fabricate edition/artwork pairings."""
    descriptor = source_descriptor("ygoprodeck", language)
    _, language_name = _language(language)
    if not isinstance(payload, Mapping) or "error" in payload:
        raise SourceError("Invalid YGOPRODeck snapshot")
    cards = _rows(payload.get("data"), "YGOPRODeck")
    meta = payload.get("meta", {})
    if not isinstance(meta, Mapping) or meta.get("next_page") or meta.get("previous_page"):
        raise SourceError("Incomplete paginated YGOPRODeck snapshot")
    if "total_rows" in meta and meta["total_rows"] != len(cards):
        raise SourceError("Incomplete paginated YGOPRODeck snapshot")
    result = []
    for card in cards:
        passcode = _numeric_id(card.get("id"))
        name = _text(card.get("name"), "card name")
        sets = card.get("card_sets", [])
        if not isinstance(sets, list) or len(sets) > 2_000:
            raise SourceError("Invalid YGOPRODeck printings")
        # Unknown printings remain a clearly incomplete logical-card reference.
        for printing in sets or [None]:
            if printing is not None and not isinstance(printing, Mapping):
                raise SourceError("Invalid YGOPRODeck printing")
            code = _text(printing.get("set_code"), "set code", max_length=160) if printing is not None else ""
            name_of_set = printing.get("set_name") if printing is not None else ""
            rarity = _nullable_text(printing.get("set_rarity"), "rarity") if printing is not None else None
            rarity_code = _nullable_text(printing.get("set_rarity_code"), "rarity code") if printing is not None else None
            # The source's separate card_images array does not map images to sets.
            # Do not inspect it, multiply rows by it, or infer finish from rarity.
            item = _record("ygoprodeck", descriptor.system_code, language_name,
                _provider_id("ygoprodeck", passcode, code, rarity, rarity_code),
                name=name, set_id=code.split("-", 1)[0], set_name=name_of_set,
                card_number=code, rarity=rarity, source_url=descriptor.source_url)
            result.append(item)
            if len(result) > MAX_NORMALIZED_ROWS:
                raise SourceError("Oversized normalized snapshot")
    return _deduplicate(result)


def normalize_lorcanajson(payload, language: str = "English") -> list[dict]:
    """Map documented v2 identifiers, language and explicit foil variants only."""
    descriptor = source_descriptor("lorcanajson", language)
    language_code, language_name = _language(language)
    if not isinstance(payload, Mapping):
        raise SourceError("Invalid LorcanaJSON snapshot")
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping) or metadata.get("language") != language_code:
        raise SourceError("LorcanaJSON language evidence mismatch")
    version = metadata.get("formatVersion")
    if not isinstance(version, str) or not re.fullmatch(r"2\.\d+\.\d+", version):
        raise SourceError("Unsupported LorcanaJSON schema version")
    generated = metadata.get("generatedOn")
    if not isinstance(generated, str):
        raise SourceError("Missing LorcanaJSON source revision")
    try:
        datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceError("Invalid LorcanaJSON source revision") from exc
    sets = payload.get("sets")
    if not isinstance(sets, Mapping):
        raise SourceError("Missing LorcanaJSON set registry")
    result = []
    for card in _rows(payload.get("cards"), "LorcanaJSON"):
        native_id = _numeric_id(card.get("id"))
        code = _text(card.get("setCode"), "set code", max_length=160)
        card_set = sets.get(code)
        if not isinstance(card_set, Mapping):
            raise SourceError("Missing LorcanaJSON set reference")
        number = card.get("fullIdentifier")
        if number is not None:
            identifier = _text(number, "full identifier", max_length=160)
            parts = [part.strip() for part in identifier.split("•")]
            if len(parts) != 3 or parts[1].casefold() != language_code:
                raise SourceError("LorcanaJSON printed-language evidence mismatch")
            number = parts[0]
        elif card.get("number") is not None:
            number = _numeric_id(card["number"]) + _text(card.get("variant"), "variant", optional=True)
        else:
            number = ""
        finishes = card.get("foilTypes")
        if finishes is None:
            finishes = [None]
        elif not isinstance(finishes, list) or not finishes or len(finishes) > 16:
            raise SourceError("Invalid LorcanaJSON finish evidence")
        for finish in finishes:
            # Literal 'None' denotes a documented non-foil option, unlike null,
            # which denotes an unknown finish. Never turn absent data into foil.
            if finish is not None:
                finish = _text(finish, "finish", max_length=160)
            result.append(_record("lorcanajson", descriptor.system_code, language_name,
                _provider_id("lorcanajson", native_id, language_code, finish),
                name=card.get("fullName"), set_id=code, set_name=card_set.get("name"),
                card_number=number, rarity=card.get("rarity"), finish=finish,
                release_date=card_set.get("releaseDate"), source_url=descriptor.source_url))
            if len(result) > MAX_NORMALIZED_ROWS:
                raise SourceError("Oversized normalized snapshot")
    return _deduplicate(result)


def normalize_scryfall(payload, language: str = "English") -> list[dict]:
    """Preserve printing UUID/finish, retain English name, exclude digital-only."""
    language_code, language_name = _language(language)
    result = []
    for card in _rows(payload, "Scryfall bulk"):
        code = _text(card.get("lang"), "printing language", max_length=16)
        if code != language_code:
            continue
        digital, games = card.get("digital"), card.get("games")
        if not isinstance(digital, bool) or not isinstance(games, list):
            raise SourceError("Missing Scryfall physical-format evidence")
        if digital or "paper" not in games:
            continue
        try:
            printing_id = str(UUID(_text(card.get("id"), "printing identifier", max_length=36)))
        except ValueError as exc:
            raise SourceError("Invalid Scryfall printing identifier") from exc
        finishes = card.get("finishes")
        if finishes is None:
            finishes = [None]
        elif not isinstance(finishes, list) or not finishes or len(finishes) > 16:
            raise SourceError("Invalid Scryfall finish evidence")
        for finish in finishes:
            if finish is not None:
                finish = _text(finish, "finish", max_length=160)
            result.append(_record("scryfall", "MAGIC_THE_GATHERING", language_name,
                _provider_id("scryfall", printing_id, finish), name=card.get("name"),
                set_id=card.get("set"), set_name=card.get("set_name"),
                card_number=card.get("collector_number"), rarity=card.get("rarity"),
                finish=finish, release_date=card.get("released_at"),
                source_url="https://api.scryfall.com/cards/" + printing_id))
            if len(result) > MAX_NORMALIZED_ROWS:
                raise SourceError("Oversized normalized snapshot")
    return _deduplicate(result)


def normalize_source(source: str, payload, language: str = "English") -> list[dict]:
    normalizers = {"ygoprodeck": normalize_ygoprodeck,
        "lorcanajson": normalize_lorcanajson, "scryfall": normalize_scryfall}
    if source == "riftcodex":
        raise DeferredSourceError("Riftcodex bulk import is deferred pending source permission review")
    if source not in normalizers:
        raise SourceError("Unknown catalogue source")
    return normalizers[source](payload, language)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("Duplicate JSON object key")
        result[key] = value
    return result


def _invalid_json_constant(value):
    raise SourceError("Invalid JSON numeric constant")


def _decode_json(content: bytes):
    try:
        return json.loads(content, object_pairs_hook=_unique_json_object,
            parse_constant=_invalid_json_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise SourceError("Invalid source JSON") from exc


def _assert_public_client(client: httpx.AsyncClient) -> None:
    # A caller must not hand an authenticated admin client to a public feed.
    if client.auth is not None or client.cookies or client.params or any(key.lower() not in {
            "accept", "accept-encoding", "connection", "user-agent"}
            for key in client.headers):
        raise SourceError("A credential-free public HTTP client is required")


async def _download(client: httpx.AsyncClient, url: str, max_bytes: int) -> bytes:
    """Only called with static locators or the separately pinned Scryfall host."""
    try:
        async with client.stream("GET", url, headers=_PUBLIC_HEADERS, auth=None,
                follow_redirects=False, timeout=SOURCE_REQUEST_TIMEOUT) as response:
            if response.status_code != 200:
                # No retries for throttling or access denials; no raw response log.
                raise SourceError(f"Source returned HTTP {response.status_code}; no retry attempted")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"application/json", "application/octet-stream", "text/json"}:
                raise SourceError("Source did not return a JSON content type")
            # Bound memory before the HTTP decoder can expand an untrusted
            # compressed body. The request explicitly asks for identity bytes.
            if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                raise SourceError("Encoded response rejected to preserve the byte bound")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > max_bytes):
                raise SourceError("Source exceeds the permitted byte bound")
            chunks, size = [], 0
            async for chunk in response.aiter_bytes(chunk_size=65_536):
                size += len(chunk)
                if size > max_bytes:
                    raise SourceError("Source exceeds the permitted byte bound")
                chunks.append(chunk)
            if not size:
                raise SourceError("Empty source response")
            return b"".join(chunks)
    except httpx.HTTPError as exc:
        raise SourceError("Source transport failed; no retry attempted") from exc


def _scryfall_bulk_url(metadata) -> str:
    if not isinstance(metadata, Mapping) or metadata.get("object") != "bulk_data" or metadata.get("type") != "default_cards":
        raise SourceError("Unexpected Scryfall bulk descriptor")
    size = metadata.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_SOURCE_BYTES:
        raise SourceError("Scryfall bulk exceeds this bounded importer; a streaming importer is required")
    url = metadata.get("download_uri")
    if not isinstance(url, str):
        raise SourceError("Missing Scryfall bulk URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "data.scryfall.io"
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/default-cards/default-cards-\d{14}\.json", parsed.path)):
        raise SourceError("Unapproved Scryfall bulk URL")
    return url


async def fetch_source(source: str, client: httpx.AsyncClient, *,
                       approved_sources: Collection[str] = (),
                       language: str = "English") -> FetchedSource:
    """Fetch once, validate completely, and return metadata plus a byte digest.

    The caller must check its permission registry, refresh interval and source
    revision before invoking this function. This function has no persistent
    cache, schedule, retries or side effects beyond bounded sequential GETs.
    REVIEW_REQUIRED sources cannot be enabled by merely adding their names to
    ``approved_sources`` in this revision; permission review needs a code change.
    """
    descriptor = source_descriptor(source, language)
    if descriptor.download_url is None:
        raise DeferredSourceError("Source downloader is deferred pending permission review")
    if (isinstance(approved_sources, (str, bytes)) or not isinstance(approved_sources, Collection)
            or source not in approved_sources
            or descriptor.permission_status != "METADATA_ACCESS_DOCUMENTED"):
        raise SourcePermissionError("Source lacks reviewed metadata-access approval")
    _assert_public_client(client)
    if source == "reviewed_figures":
        from .r2_first_figures import fetch_figures
        return await fetch_figures(client, descriptor)
    if source == "lorcast":
        from .r2_first_lorcast import fetch_lorcast
        return await fetch_lorcast(client, descriptor)
    if source == "mtgjson":
        from .r2_first_mtgjson import fetch_mtgjson
        return await fetch_mtgjson(client, descriptor)
    if source == "cardcollectorcapital":
        from .r2_first_sports import fetch_sports
        return await fetch_sports(client, descriptor)
    if source == "cardcollectorcapital_heritage":
        from .r2_first_topps_heritage import fetch_topps_heritage
        return await fetch_topps_heritage(client, descriptor)
    try:
        async with asyncio.timeout(TOTAL_DOWNLOAD_TIMEOUT_SECONDS):
            url = descriptor.download_url
            if source == "scryfall":
                # Kept fail-closed behind the descriptor's permission review.
                metadata = _decode_json(await _download(client, url, 128_000))
                url = _scryfall_bulk_url(metadata)
            content = await _download(client, url, descriptor.max_bytes)
    except TimeoutError as exc:
        raise SourceError("Source exceeded its total download time bound") from exc
    digest = hashlib.sha256(content).hexdigest()
    records = normalize_source(source, _decode_json(content), language)
    return FetchedSource(descriptor.provider, descriptor.system_code, descriptor.source_url,
        "sha256:" + digest, digest, records)
