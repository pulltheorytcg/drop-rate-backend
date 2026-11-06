"""Bounded MTGJSON printing metadata; no artwork, pricing or business writes.

Provider evidence reviewed 2026-11-04: https://mtgjson.com/license/ explicitly
applies MIT to the website and its content. Keep its copyright/permission notice
with substantial distributed extracts. This does not grant third-party artwork,
rules/flavour-text or trademark rights. Only whitelisted factual fields survive.

AllPrintings is larger than the ordinary source downloader's entire byte budget.
The fixed XZ file is streamed to a private temporary file and checksum-verified
before incremental parsing. A bounded per-set metadata spool handles set headers
that occur AFTER cards. No complete expanded document or complete set is held in
memory. Parsing runs off the event loop and cooperatively stops on cancellation.

Requires the primary-verified ijson==3.6.0 release. The registry/caller still owns
source approval, refresh scheduling and publication; this module owns none.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from functools import partial
import hashlib
import json
import lzma
import re
import sys
import tempfile
import threading
import time
from typing import BinaryIO
import unicodedata
from uuid import UUID

import httpx
import ijson

from . import r2_first_catalogue as codec
from .r2_first_sources import (
    FetchedSource, SourceDescriptor, SourceError, SourcePermissionError,
    _assert_public_client,
)


DOWNLOAD_URL = "https://mtgjson.com/api/v5/AllPrintings.json.xz"
CHECKSUM_URL = DOWNLOAD_URL + ".sha256"
PERMISSION_REF = "https://mtgjson.com/license/"
SOURCE_REVISION = "all-printings-v5-metadata-v2-mcm-id"
PROVIDER = "mtgjson"
SYSTEM_CODE = "MAGIC_THE_GATHERING"
SOURCE_DETAILS = {
    "source_credit": "Copyright (c) 2018–Present Zach Halpern",
    "source_license": "MIT",
    "source_license_url": PERMISSION_REF,
}

# Source-specific limits: none relax the existing catalogue codec's limits.
MAX_COMPRESSED_BYTES = 128_000_000
MAX_EXPANDED_BYTES = 900_000_000
MAX_SOURCE_ROWS = 400_000
MAX_SETS = 10_000
MAX_SET_SPOOL_BYTES = 32_000_000
MAX_OUTPUT_MEMORY_BYTES = 384_000_000
MAX_LZMA_MEMORY_BYTES = 96_000_000
MAX_TOKEN_BYTES = 65_536
MAX_ATOM_BYTES = 128
MAX_JSON_DEPTH = 32
MAX_JSON_EVENTS = 80_000_000
MAX_CHECKSUM_BYTES = 128
CHUNK_BYTES = 65_536
TOTAL_TIMEOUT_SECONDS = 360
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0, pool=10.0)
_HEADERS = {
    "User-Agent": "DropRateMetadataImport/1.0 (+https://app.droprate.co.uk)",
    "Accept": "application/octet-stream, text/plain",
    "Accept-Encoding": "identity",
}
_SET_CODE = re.compile(r"[A-Z0-9_]{1,16}\Z")
_STRING_SPECIAL = re.compile(rb'["\\]')
_ATOM_END = re.compile(rb'["{}\[\],:\x20\t\r\n]')
_CARD_SCALARS = frozenset({
    "uuid", "name", "number", "language", "rarity", "setCode", "side", "isOnlineOnly",
    "originalReleaseDate",
})
_CARD_ARRAYS = frozenset({"availability", "finishes"})
_SET_SCALARS = frozenset({"code", "name", "releaseDate", "isOnlineOnly"})
_FINISH_TOKEN = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")


@dataclass(frozen=True, slots=True)
class ParsedMtgjson:
    records: list[dict]
    build_date: str
    build_version: str
    source_rows: int
    normalized_raw_bytes: int
    estimated_output_memory_bytes: int


def _check_time(deadline: float, cancelled: threading.Event | None) -> None:
    if (cancelled is not None and cancelled.is_set()) or time.monotonic() >= deadline:
        raise SourceError("MTGJSON exceeded its total time bound or was cancelled")


def _text(value, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise SourceError(f"Invalid MTGJSON {field}")
    value = unicodedata.normalize("NFC", value).strip()
    if (not value or len(value) > maximum
            or any(unicodedata.category(char).startswith("C") for char in value)):
        raise SourceError(f"Invalid MTGJSON {field}")
    return value


def _date(value, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise SourceError(f"Invalid MTGJSON {field}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SourceError(f"Invalid MTGJSON {field}") from exc
    return value


def _canonical_uuid(value) -> str:
    if not isinstance(value, str):
        raise SourceError("Invalid MTGJSON printing UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise SourceError("Invalid MTGJSON printing UUID") from exc
    if str(parsed) != value or parsed.int == 0:
        raise SourceError("Invalid MTGJSON printing UUID")
    return value


def _structural_field(value) -> None:
    # ijson's dotted prefixes are NOT escaped paths. A literal object key such
    # as "finishes.item" otherwise impersonates an array member. Only the
    # root/metadata/set/card maps drive this parser, so reject dotted keys at
    # those real map boundaries BEFORE interpreting their subsequent prefixes.
    # Unknown nested provider metadata stays ignored and may have dotted keys.
    if not isinstance(value, str) or not value or "." in value:
        raise SourceError("Invalid dotted MTGJSON structural field")


class _TokenBound:
    """Reject huge tokens BEFORE the JSON parser accumulates their contents.

    This scans runs rather than each byte in Python. Escapes may cross read
    boundaries. JSON syntax/UTF-8 validation remains the parser's responsibility.
    """

    def __init__(self):
        self.in_string = False
        self.escaped = False
        self.token_bytes = 0

    def check(self, chunk: bytes) -> None:
        offset = 0
        while offset < len(chunk):
            if self.in_string:
                if self.escaped:
                    self.token_bytes += 1
                    self.escaped = False
                    offset += 1
                    if self.token_bytes > MAX_TOKEN_BYTES:
                        raise SourceError("MTGJSON JSON token exceeds memory bound")
                    continue
                match = _STRING_SPECIAL.search(chunk, offset)
                end = match.start() if match else len(chunk)
                self.token_bytes += end - offset
                if self.token_bytes > MAX_TOKEN_BYTES:
                    raise SourceError("MTGJSON JSON token exceeds memory bound")
                offset = end
                if match is None:
                    break
                if chunk[offset] == 34:
                    self.in_string = False
                    self.token_bytes = 0
                else:
                    self.escaped = True
                    self.token_bytes += 1
                offset += 1
            else:
                match = _ATOM_END.search(chunk, offset)
                end = match.start() if match else len(chunk)
                self.token_bytes += end - offset
                if self.token_bytes > MAX_ATOM_BYTES:
                    raise SourceError("MTGJSON JSON atom exceeds memory bound")
                offset = end
                if match is None:
                    break
                self.token_bytes = 0
                self.in_string = chunk[offset] == 34
                offset += 1


class _BoundedXZReader:
    """One XZ stream, small read buffers, bounded dictionary/expansion/tokens."""

    def __init__(self, source: BinaryIO, deadline: float, cancelled: threading.Event | None):
        self.source = source
        self.deadline = deadline
        self.cancelled = cancelled
        self.decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ,
                                             memlimit=MAX_LZMA_MEMORY_BYTES)
        self.expanded = 0
        self.compressed = 0
        self.finished = False
        self.tokens = _TokenBound()

    def read(self, size: int = CHUNK_BYTES) -> bytes:
        if size == 0:
            return b""
        if size < 0 or size > CHUNK_BYTES:
            raise SourceError("Unbounded MTGJSON reader request rejected")
        _check_time(self.deadline, self.cancelled)
        if self.finished:
            return b""
        while True:
            compressed = b""
            if self.decoder.needs_input:
                compressed = self.source.read(CHUNK_BYTES)
                if not compressed:
                    raise SourceError("Truncated MTGJSON XZ stream")
                self.compressed += len(compressed)
                if self.compressed > MAX_COMPRESSED_BYTES:
                    raise SourceError("MTGJSON exceeds compressed byte bound")
            try:
                output = self.decoder.decompress(compressed, max_length=size)
            except lzma.LZMAError as exc:
                raise SourceError("Invalid MTGJSON XZ stream or dictionary memory bound") from exc
            self.expanded += len(output)
            if self.expanded > MAX_EXPANDED_BYTES:
                raise SourceError("MTGJSON exceeds expanded byte bound")
            self.tokens.check(output)
            if self.decoder.eof:
                # Reject concatenated streams/trailing bytes; a checksum alone
                # must not allow a second, unparsed document to be ignored.
                if self.decoder.unused_data or self.source.read(1):
                    raise SourceError("Trailing data after MTGJSON XZ stream")
                self.finished = True
            if output or self.finished:
                return output
            _check_time(self.deadline, self.cancelled)


def _checked_events(reader: _BoundedXZReader) -> Iterator[tuple[str, str, object]]:
    """Duplicate-key, depth and event-count guards also apply to ignored fields."""
    stack: list[set[str] | None] = []
    try:
        events = ijson.parse(reader, buf_size=CHUNK_BYTES, use_float=True,
                             multiple_values=False, allow_comments=False)
        for count, (prefix, event, value) in enumerate(events, 1):
            if count > MAX_JSON_EVENTS:
                raise SourceError("MTGJSON exceeds JSON event bound")
            if count % 1024 == 0:
                _check_time(reader.deadline, reader.cancelled)
            if event in {"start_map", "start_array"}:
                stack.append(set() if event == "start_map" else None)
                if len(stack) > MAX_JSON_DEPTH:
                    raise SourceError("MTGJSON exceeds JSON depth bound")
            elif event == "map_key":
                keys = stack[-1] if stack else None
                if keys is None or value in keys:
                    raise SourceError("Duplicate or invalid MTGJSON JSON object key")
                if len(keys) >= MAX_SETS:
                    raise SourceError("MTGJSON JSON object exceeds key bound")
                keys.add(value)
            elif event in {"end_map", "end_array"}:
                if not stack:
                    raise SourceError("Invalid MTGJSON JSON structure")
                stack.pop()
            yield prefix, event, value
    except (ijson.JSONError, UnicodeError, OverflowError, RecursionError) as exc:
        raise SourceError("Invalid MTGJSON JSON snapshot") from exc
    if stack or not reader.finished:
        raise SourceError("Incomplete MTGJSON JSON snapshot")


def _selected_card(card: dict, set_code: str) -> dict | None:
    required = {"uuid", "name", "number", "language", "rarity", "setCode",
                "availability", "finishes"}
    if not required <= card.keys():
        raise SourceError("Missing MTGJSON printing identity evidence")
    native_id = _canonical_uuid(card["uuid"])
    name = _text(card["name"], "card name")
    number = _text(card["number"], "collector number", 128)
    language = _text(card["language"], "language", 32)
    rarity = _text(card["rarity"], "rarity", 128)
    if card["setCode"] != set_code:
        raise SourceError("MTGJSON card/set identity mismatch")
    online_only = card.get("isOnlineOnly", False)
    if type(online_only) is not bool:
        raise SourceError("Invalid MTGJSON online-only evidence")
    availability = card["availability"]
    finishes = card["finishes"]
    if (not isinstance(availability, list)
            or any(type(item) is not str for item in availability)
            or len(set(availability)) != len(availability)
            or any(re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", item) is None for item in availability)):
        raise SourceError("Invalid MTGJSON physical-format evidence")
    if (not isinstance(finishes, list)
            or any(type(item) is not str for item in finishes)
            or len(set(finishes)) != len(finishes)):
        raise SourceError("Invalid MTGJSON finish evidence")
    side = card.get("side")
    if side is not None and (not isinstance(side, str) or not re.fullmatch(r"[a-z]", side)):
        raise SourceError("Invalid MTGJSON face evidence")
    if language != "English" or "paper" not in availability or online_only or side not in {None, "a"}:
        return None
    # Real arena-only rows explicitly have finishes=[] (e.g. MBC). Their
    # absence is not a malformed physical printing; they were excluded above.
    # Every retained paper printing still needs explicit valid finish labels.
    # Preserve provider tokens (including PTC's "signed"); do not silently
    # reinterpret them as one of another provider's three finish categories.
    if not finishes or any(_FINISH_TOKEN.fullmatch(finish) is None for finish in finishes):
        raise SourceError("Invalid MTGJSON physical finish evidence")
    # MTGJSON exposes its exact Cardmarket product identifier in
    # identifiers.mcmId. Keep only validated literal provider IDs; null,
    # placeholders, booleans and malformed IDs are NOT eligible for joins.
    # This is identity evidence only, never a source price or a valuation.
    raw_mcm = card.get("mcmId")
    mcm_id = None
    if (type(raw_mcm) is int and 0 < raw_mcm <= 2**31-1):
        mcm_id = str(raw_mcm)
    elif (type(raw_mcm) is str and raw_mcm.isascii() and
          re.fullmatch(r"[1-9][0-9]{0,9}", raw_mcm) and int(raw_mcm) <= 2**31-1):
        mcm_id = raw_mcm
    # MTGJSON explicitly uses this for promotions outside the set's cycle,
    # including Secret Lair. Otherwise retain the enclosing set's release date.
    release = card.get("originalReleaseDate")
    if release is not None:
        release = _date(release, "printing release date")
    return {"uuid": native_id, "name": name, "number": number,
            "rarity": rarity, "finishes": sorted(finishes), "release_date": release,
            "cardmarket_product_id": mcm_id}


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _record_memory(row: dict) -> int:
    # Conservative accounting: even shared string values are charged per row.
    # Include dict/list/set entry overhead; parser buffers/dictionary have their
    # own independent limits. This is not a process-wide RSS guarantee.
    return (sys.getsizeof(row) + sys.getsizeof(row["details"]) + 96
            + sum(sys.getsizeof(value) for value in row.values() if isinstance(value, str))
            + sum(sys.getsizeof(value) for value in row["details"].values()))


def parse_mtgjson(source: BinaryIO, *, deadline: float | None = None,
                 cancelled: threading.Event | None = None) -> ParsedMtgjson:
    """Parse one checksum-verified XZ stream without persistent side effects.

    Exposed for deterministic offline tests. Network callers must use
    ``fetch_mtgjson`` so checksum, locator, permission and HTTP guards apply.
    """
    deadline = deadline if deadline is not None else time.monotonic() + TOTAL_TIMEOUT_SECONDS
    reader = _BoundedXZReader(source, deadline, cancelled)
    metadata: dict = {}
    root_fields: set[str] = set()
    set_fields: dict = {}
    current_set: str | None = None
    set_prefix = card_prefix = ""
    card: dict | None = None
    cards_seen = root_started = root_finished = False
    source_rows = set_count = spool_size = raw_bytes = output_memory = 0
    records: list[dict] = []
    seen_printings: set[str] = set()

    with tempfile.TemporaryFile(mode="w+b", prefix="drop-rate-mtgjson-set-") as spool:
        for prefix, event, value in _checked_events(reader):
            if prefix == "":
                if event == "start_map" and not root_started:
                    root_started = True
                elif event == "map_key":
                    _structural_field(value)
                    if value not in {"meta", "data"}:
                        raise SourceError("Unexpected MTGJSON root field")
                    root_fields.add(value)
                elif event == "end_map":
                    root_finished = True
                else:
                    raise SourceError("MTGJSON root must be an object")
            elif prefix == "meta":
                if event == "map_key":
                    _structural_field(value)
                if event not in {"start_map", "map_key", "end_map"}:
                    raise SourceError("MTGJSON metadata must be an object")
            elif prefix.startswith("meta."):
                field = prefix.removeprefix("meta.")
                if field not in {"date", "version"} or event != "string":
                    raise SourceError("Invalid MTGJSON source revision schema")
                metadata[field] = value
            elif prefix == "data":
                if event == "map_key":
                    if current_set is not None or not isinstance(value, str) or not _SET_CODE.fullmatch(value):
                        raise SourceError("Invalid MTGJSON set registry")
                    set_count += 1
                    if set_count > MAX_SETS:
                        raise SourceError("MTGJSON exceeds set count bound")
                    current_set = value
                    set_prefix = "data." + value
                    card_prefix = set_prefix + ".cards.item"
                    set_fields, cards_seen, spool_size = {}, False, 0
                    spool.seek(0)
                    spool.truncate()
                elif event not in {"start_map", "end_map"}:
                    raise SourceError("MTGJSON data must be a set map")
            elif current_set is not None:
                if prefix == set_prefix:
                    if event == "map_key":
                        _structural_field(value)
                    if event == "end_map":
                        if not cards_seen or not _SET_SCALARS <= set_fields.keys():
                            raise SourceError("Missing MTGJSON set identity evidence")
                        if set_fields["code"] != current_set or type(set_fields["isOnlineOnly"]) is not bool:
                            raise SourceError("Invalid MTGJSON set identity evidence")
                        set_name = _text(set_fields["name"], "set name")
                        release_date = _date(set_fields["releaseDate"], "release date")
                        if not set_fields["isOnlineOnly"]:
                            spool.seek(0)
                            for line in spool:
                                _check_time(deadline, cancelled)
                                item = json.loads(line)
                                native_id = item["uuid"]
                                if native_id in seen_printings:
                                    raise SourceError("Duplicate MTGJSON printing identity")
                                seen_printings.add(native_id)
                                for finish in item["finishes"]:
                                    row = {"provider": PROVIDER, "system_code": SYSTEM_CODE,
                                        "language": "English", "provider_id": f"mtgjson:{native_id}:{finish}",
                                        "product_type": "CARD", "name": item["name"],
                                        "set_id": current_set, "set_name": set_name,
                                        "card_number": item["number"], "rarity": item["rarity"],
                                        "finish": finish, "release_date": item["release_date"] or release_date,
                                        "source_url": DOWNLOAD_URL, "details": dict(SOURCE_DETAILS)}
                                    # Each finish retains the same source print ID,
                                    # and the downstream pricing match must still
                                    # check the exact finish and set/edition.
                                    if item["cardmarket_product_id"] is not None:
                                        row["details"]["cardmarket_product_id"] = item["cardmarket_product_id"]
                                    count = len(records) + 1
                                    if count > codec.MAX_ROWS:
                                        raise SourceError("MTGJSON exceeds catalogue row bound; no truncation")
                                    stored = {**row, "key": codec.stable_key(PROVIDER, SYSTEM_CODE,
                                                                            "English", row["provider_id"])}
                                    # Exact JSON-array framing for codec's 500-row
                                    # parts (bounded field sizes cannot hit 4 MB).
                                    raw_bytes += len(_json(stored)) + 1 + ((count - 1) % codec.MAX_PART_ROWS == 0)
                                    if raw_bytes > codec.MAX_RAW_BYTES:
                                        raise SourceError("MTGJSON exceeds catalogue byte bound; no truncation")
                                    output_memory += _record_memory(row)
                                    if output_memory > MAX_OUTPUT_MEMORY_BYTES:
                                        raise SourceError("MTGJSON exceeds output memory bound")
                                    records.append(row)
                        current_set = None
                    elif event not in {"start_map", "map_key"}:
                        raise SourceError("MTGJSON set must be an object")
                elif prefix == set_prefix + ".cards":
                    if event == "start_array":
                        cards_seen = True
                    elif event != "end_array":
                        raise SourceError("MTGJSON cards must be an array")
                elif prefix == card_prefix:
                    if event == "map_key":
                        _structural_field(value)
                    if event == "start_map":
                        card = {}
                        source_rows += 1
                        if source_rows > MAX_SOURCE_ROWS:
                            raise SourceError("MTGJSON exceeds source row bound")
                    elif event == "end_map":
                        if card is None:
                            raise SourceError("Invalid MTGJSON card boundary")
                        selected = _selected_card(card, current_set)
                        if selected is not None:
                            line = _json(selected) + b"\n"
                            spool_size += len(line)
                            if spool_size > MAX_SET_SPOOL_BYTES:
                                raise SourceError("MTGJSON exceeds per-set spool bound")
                            spool.write(line)
                        card = None
                    elif event != "map_key":
                        raise SourceError("MTGJSON card must be an object")
                elif card is not None and prefix.startswith(card_prefix + "."):
                    field = prefix[len(card_prefix) + 1:]
                    if field in _CARD_SCALARS:
                        if event not in {"string", "boolean", "null"}:
                            raise SourceError("Invalid MTGJSON card scalar")
                        card[field] = value
                    elif field == "identifiers.mcmId":
                        if event not in {"string", "number", "null", "boolean"}:
                            raise SourceError("Malformed MTGJSON Cardmarket ID structure")
                        card["mcmId"] = value
                    elif field in _CARD_ARRAYS:
                        if event == "start_array":
                            card[field] = []
                        elif event != "end_array":
                            raise SourceError("Invalid MTGJSON card array")
                    elif field.endswith(".item") and field[:-5] in _CARD_ARRAYS:
                        field = field[:-5]
                        if event != "string" or len(card[field]) >= 16:
                            raise SourceError("Invalid MTGJSON card array member")
                        card[field].append(value)
                else:
                    field = prefix[len(set_prefix) + 1:] if prefix.startswith(set_prefix + ".") else ""
                    if field in _SET_SCALARS:
                        if event not in {"string", "boolean"}:
                            raise SourceError("Invalid MTGJSON set scalar")
                        set_fields[field] = value

    if (not root_started or not root_finished or root_fields != {"meta", "data"}
            or current_set is not None or set_count == 0 or not records
            or metadata.keys() != {"date", "version"}):
        raise SourceError("Empty or incomplete MTGJSON snapshot")
    build_date = _date(metadata["date"], "build date")
    version = _text(metadata["version"], "build version", 64)
    if not re.fullmatch(r"5\.\d+\.\d+\+\d{8}", version) or version.rsplit("+", 1)[1] != build_date.replace("-", ""):
        raise SourceError("Unsupported or inconsistent MTGJSON build revision")
    _check_time(deadline, cancelled)
    return ParsedMtgjson(records, build_date, version, source_rows, raw_bytes, output_memory)


async def _download_to(client: httpx.AsyncClient, url: str, destination: BinaryIO,
                       maximum: int, *, checksum: bool = False) -> tuple[str, int]:
    _assert_public_client(client)
    if any(client.event_hooks.values()):
        raise SourceError("MTGJSON requires a hook-free public HTTP client")
    digest, size = hashlib.sha256(), 0
    try:
        async with client.stream("GET", url, headers=_HEADERS, auth=None,
                                 follow_redirects=False, timeout=REQUEST_TIMEOUT) as response:
            if response.status_code != 200:
                raise SourceError(f"MTGJSON returned HTTP {response.status_code}; no retry attempted")
            media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            accepted = {"text/plain", "application/octet-stream"} if checksum else {
                "application/octet-stream", "application/x-xz", "application/xz"}
            if media_type not in accepted:
                raise SourceError("Unexpected MTGJSON response content type")
            if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                raise SourceError("Encoded MTGJSON response rejected")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or not 0 < int(length) <= maximum):
                raise SourceError("MTGJSON exceeds download byte bound")
            async for chunk in response.aiter_bytes(chunk_size=CHUNK_BYTES):
                size += len(chunk)
                if size > maximum:
                    raise SourceError("MTGJSON exceeds download byte bound")
                digest.update(chunk)
                destination.write(chunk)
            if not size or (length is not None and size != int(length)):
                raise SourceError("Empty or truncated MTGJSON response")
    except httpx.HTTPError as exc:
        raise SourceError("MTGJSON transport failed; no retry attempted") from exc
    return digest.hexdigest(), size


async def fetch_mtgjson(client: httpx.AsyncClient, descriptor: SourceDescriptor) -> FetchedSource:
    """Two fixed credential-free GETs, verified metadata, no retries/publication."""
    if (descriptor.provider != PROVIDER or descriptor.system_code != SYSTEM_CODE
            or descriptor.source_url != DOWNLOAD_URL or descriptor.download_url != DOWNLOAD_URL
            or descriptor.source_revision != SOURCE_REVISION or descriptor.permission_ref != PERMISSION_REF
            or descriptor.permission_status != "METADATA_ACCESS_DOCUMENTED"
            or type(descriptor.max_bytes) is not int or not 0 < descriptor.max_bytes <= MAX_COMPRESSED_BYTES):
        raise SourcePermissionError("MTGJSON descriptor lacks reviewed fixed-source approval")
    _assert_public_client(client)
    deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
    cancelled = threading.Event()
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            with tempfile.TemporaryFile(mode="w+b", prefix="drop-rate-mtgjson-sha-") as checksum:
                await _download_to(client, CHECKSUM_URL, checksum, MAX_CHECKSUM_BYTES, checksum=True)
                checksum.seek(0)
                expected = checksum.read(MAX_CHECKSUM_BYTES).strip()
                if re.fullmatch(rb"[0-9a-f]{64}", expected) is None:
                    raise SourceError("Invalid MTGJSON checksum document")
            # No caller-controlled path or credentials enter the temporary file.
            with tempfile.TemporaryFile(mode="w+b", prefix="drop-rate-mtgjson-") as compressed:
                digest, _ = await _download_to(client, DOWNLOAD_URL, compressed, descriptor.max_bytes)
                if digest != expected.decode("ascii"):
                    raise SourceError("MTGJSON source checksum mismatch; no retry attempted")
                compressed.seek(0)
                # An executor Future (unlike a create_task(to_thread(...))
                # wrapper) is not independently cancelled by all_tasks-based
                # application shutdown. Its completion therefore continues to
                # mean the actual file-using worker has stopped.
                task = asyncio.get_running_loop().run_in_executor(None,
                    partial(parse_mtgjson, compressed, deadline=deadline, cancelled=cancelled))
                try:
                    parsed = await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled.set()
                    # Every additional cancel() can interrupt shield's await,
                    # not the worker. Drain it in a cancellation-resilient loop
                    # before leaving TemporaryFile. Preserve the caller's
                    # original cancellation and retrieve any worker exception.
                    while not task.done():
                        try:
                            await asyncio.shield(task)
                        except asyncio.CancelledError:
                            continue
                        except Exception:
                            break
                    try:
                        task.result()
                    except (Exception, asyncio.CancelledError):
                        pass
                    raise
    except TimeoutError as exc:
        raise SourceError("MTGJSON exceeded its total time bound") from exc
    except OSError as exc:
        raise SourceError("MTGJSON temporary storage failed") from exc
    revision = f"{SOURCE_REVISION};build={parsed.build_date};version={parsed.build_version};sha256:{digest}"
    return FetchedSource(PROVIDER, SYSTEM_CODE, DOWNLOAD_URL, revision, digest, parsed.records)
