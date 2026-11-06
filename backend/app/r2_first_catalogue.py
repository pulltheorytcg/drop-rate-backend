"""Closed-schema, metadata-only catalogues written directly to private R2.

This is NOT an inventory, ownership, price or identity-approval database. The
authenticated PostgreSQL registry owns the approved manifest digest; callers
must verify its provider/scope/revision/rights bindings before serving it. A
permission reference records a separately reviewed decision, not a new licence.

Files are immutable and content addressed. Publication returns only after all
parts AND the manifest have been read back. A missing/corrupt generation fails
closed; there is deliberately no fallback to nonexistent PostgreSQL rows.
SQLite is a disposable, bounded-page-cache search index, rebuilt solely from
verified R2 bytes. The registry/cache owner must close an obsolete Snapshot.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from typing import Iterable
import unicodedata
from urllib.parse import unquote, urlsplit

from .catalogue_browse_groups import group_for, validate_browse_group


SCHEMA = "drop-rate-r2-first-catalogue-v1"
MAX_ROWS = 250_000
MAX_RAW_BYTES = 128_000_000
MAX_PART_ROWS = 500
MAX_PART_BYTES = 4_000_000
MAX_PARTS = 1024
MAX_MANIFEST_BYTES = 1_000_000
MAX_RESULT_ROWS = 100
MAX_OWNED_KEYS = 10_000

ROW_FIELDS = frozenset({
    "provider", "system_code", "language", "provider_id", "product_type",
    "name", "set_id", "set_name", "card_number", "rarity", "finish",
    "release_date", "source_url",
})
DETAIL_FIELDS = frozenset({
    "edition", "variant", "artist", "player", "team", "sport", "brand",
    "franchise", "series", "manufacturer",
    "source_record_id", "source_evidence_url", "source_reviewed_at", "source_page",
    "source_credit", "source_license", "source_license_url", "source_note", "checklist_section",
    "reference_scope", "source_year", "character", "product_line", "scale",
    "manufacturer_sku", "barcode_gtin", "box_number",
    # Source identity only, never a market price or ownership signal.
    "cardmarket_product_id",
})
MANIFEST_FIELDS = frozenset({
    "schema", "provider", "system_code", "language", "source_url",
    "source_revision", "permission_ref", "record_count", "raw_bytes",
    "content_sha256", "parts",
})
PART_FIELDS = frozenset({
    "ordinal", "sha256", "raw_bytes", "rows", "first_key", "last_key",
})
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_KEY = re.compile(r"x:[0-9a-f]{64}\Z")
_PROVIDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SYSTEM = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
_LANGUAGE = re.compile(r"[A-Za-z][A-Za-z0-9 -]{0,31}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class R2FirstCatalogueError(ValueError):
    """A source, manifest or object is invalid; never serve a partial result."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise R2FirstCatalogueError(message)


def _json(value) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise R2FirstCatalogueError("Invalid catalogue JSON") from exc


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "Duplicate JSON field")
        value[key] = item
    return value


def _reject_constant(_):
    raise R2FirstCatalogueError("Non-finite JSON value")


def _decode(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise R2FirstCatalogueError("Invalid catalogue JSON") from exc


def _text(value, label: str, maximum: int, *, empty=False) -> str:
    _require(type(value) is str, f"Invalid {label}")
    _require((empty or bool(value)) and len(value) <= maximum
             and value == value.strip()
             and all(not unicodedata.category(char).startswith("C") for char in value),
             f"Invalid {label}")
    return value


def _scope(provider, system_code, language) -> tuple[str, str, str]:
    for value, pattern, name in ((provider, _PROVIDER, "provider"),
                                 (system_code, _SYSTEM, "system code"),
                                 (language, _LANGUAGE, "language")):
        _require(type(value) is str and pattern.fullmatch(value) is not None,
                 f"Invalid {name}")
        _text(value, name, 64)
    return provider, system_code, language


def _source_url(value) -> str:
    value = _text(value, "source URL", 2048)
    _require("\\" not in value and not any(char.isspace() for char in value),
             "Invalid source URL")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise R2FirstCatalogueError("Invalid source URL") from exc
    _require(parsed.scheme == "https" and bool(host) and parsed.username is None
             and parsed.password is None and port is None and not parsed.query
             and not parsed.fragment and "?" not in value and "#" not in value,
             "Source URL must be public HTTPS without credentials, query or fragment")
    _require(host.isascii() and "." in host and not host.endswith(".")
             and len(host) <= 253
             and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                     for label in host.split(".")), "Invalid source URL hostname")
    _require(not host.lower().endswith((".localhost", ".local", ".internal", ".lan",
                                       ".home", ".corp", ".test", ".invalid", ".onion")),
             "Source URL hostname is not public")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise R2FirstCatalogueError("Source URL must use a public DNS hostname")
    # Reject unusual numeric IPv4 spellings and escaped control characters too.
    _require(not all(char in "0123456789." for char in host), "Invalid source URL hostname")
    decoded = unquote(value)
    _require(not any(unicodedata.category(char).startswith("C") for char in decoded),
             "Invalid source URL escape")
    return value


def stable_key(provider: str, system_code: str, language: str, provider_id: str) -> str:
    """Exact identity tuple; names, numbers and similar printings never merge."""
    _scope(provider, system_code, language)
    _text(provider_id, "provider ID", 256)
    return "x:" + hashlib.sha256(_json([provider, system_code, language, provider_id])).hexdigest()


def _row(value, scope, *, stored=False) -> dict:
    _require(type(value) is dict, "Catalogue row must be an object")
    required = ROW_FIELDS | ({"key"} if stored else set())
    _require(required <= value.keys() and value.keys() <= required | {"details"},
             "Unexpected or missing catalogue row fields")
    _require(tuple(value[field] for field in ("provider", "system_code", "language")) == scope,
             "Catalogue row belongs to another source partition")
    _scope(*scope)
    row = {field: value[field] for field in ROW_FIELDS}
    for field, maximum, empty in (("provider_id", 256, False), ("name", 512, False),
                                  ("set_id", 256, True), ("set_name", 512, True),
                                  ("card_number", 128, True)):
        _text(row[field], field, maximum, empty=empty)
    _require(row["product_type"] in ("CARD", "FIGURE"), "Unsupported catalogue product type")
    for field in ("rarity", "finish"):
        if row[field] is not None:
            _text(row[field], field, 128)
    if row["release_date"] is not None:
        _require(type(row["release_date"]) is str and _DATE.fullmatch(row["release_date"]),
                 "Invalid release date")
        try:
            date.fromisoformat(row["release_date"])
        except ValueError as exc:
            raise R2FirstCatalogueError("Invalid release date") from exc
    _source_url(row["source_url"])
    if "details" in value:
        details = value["details"]
        _require(type(details) is dict and details.keys() <= DETAIL_FIELDS,
                 "Unexpected catalogue details")
        row["details"] = {key: _text(item, "detail", 256) for key, item in details.items()}
    row["key"] = stable_key(*scope, row["provider_id"])
    if stored:
        _require(value["key"] == row["key"], "Catalogue identity digest mismatch")
    return row


def _positive_int(value, maximum, label):
    _require(type(value) is int and 0 < value <= maximum, f"Invalid {label}")


def _digest(value, label):
    _require(type(value) is str and _DIGEST.fullmatch(value), f"Invalid {label}")


def validate_manifest(value) -> dict:
    """Validate only structural integrity; the registry authorizes this digest."""
    _require(type(value) is dict and value.keys() == MANIFEST_FIELDS,
             "Unexpected or missing manifest fields")
    _require(value["schema"] == SCHEMA, "Unsupported catalogue manifest schema")
    _scope(value["provider"], value["system_code"], value["language"])
    _source_url(value["source_url"])
    _text(value["source_revision"], "source revision", 256)
    _text(value["permission_ref"], "permission reference", 512)
    _positive_int(value["record_count"], MAX_ROWS, "catalogue row count")
    _positive_int(value["raw_bytes"], MAX_RAW_BYTES, "catalogue byte count")
    _digest(value["content_sha256"], "catalogue content digest")
    parts = value["parts"]
    _require(type(parts) is list and 0 < len(parts) <= MAX_PARTS, "Invalid manifest parts")
    total_rows = total_bytes = 0
    previous_key = ""
    seen = set()
    for ordinal, part in enumerate(parts):
        _require(type(part) is dict and part.keys() == PART_FIELDS, "Invalid part fields")
        _require(type(part["ordinal"]) is int and part["ordinal"] == ordinal,
                 "Invalid part ordering")
        _digest(part["sha256"], "part digest")
        _require(part["sha256"] not in seen, "Duplicate catalogue part")
        seen.add(part["sha256"])
        _positive_int(part["rows"], MAX_PART_ROWS, "part row count")
        _positive_int(part["raw_bytes"], MAX_PART_BYTES, "part byte count")
        for field in ("first_key", "last_key"):
            _require(type(part[field]) is str and _KEY.fullmatch(part[field]), "Invalid part key range")
        _require(previous_key < part["first_key"] <= part["last_key"], "Invalid part key ordering")
        _require((part["first_key"] == part["last_key"]) == (part["rows"] == 1),
                 "Part key range disagrees with row count")
        previous_key = part["last_key"]
        total_rows += part["rows"]
        total_bytes += part["raw_bytes"]
    _require(total_rows == value["record_count"] and total_bytes == value["raw_bytes"],
             "Manifest counts do not match parts")
    raw = _json(value)
    _require(len(raw) <= MAX_MANIFEST_BYTES, "Catalogue manifest exceeds bound")
    return _decode(raw)  # no mutable aliases to a caller's publication pointer


def canonical_manifest_bytes(manifest: dict) -> bytes:
    return _json(validate_manifest(manifest))


def manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


@dataclass(frozen=True)
class PreparedCatalogue:
    """Immutable bounded bytes; callers never choose an object key."""

    _manifest_bytes: bytes
    parts: tuple[bytes, ...]

    @property
    def manifest(self) -> dict:
        return _decode(self._manifest_bytes)

    @property
    def manifest_digest(self) -> str:
        return hashlib.sha256(self._manifest_bytes).hexdigest()


def _temporary_connection():
    directory = tempfile.TemporaryDirectory(prefix="drop-rate-r2-first-")
    try:
        connection = sqlite3.connect(str(Path(directory.name) / "catalogue.sqlite"),
                                     check_same_thread=False)
        connection.execute("pragma cache_size=-8192")
        connection.execute("pragma mmap_size=0")
        connection.execute("pragma temp_store=FILE")
        connection.execute("pragma trusted_schema=OFF")
        return directory, connection
    except BaseException:
        directory.cleanup()
        raise


def prepare_catalogue(rows: Iterable[dict], *, provider: str, system_code: str,
                      language: str, source_url: str, source_revision: str,
                      permission_ref: str) -> PreparedCatalogue:
    """Validate/sort locally, never insert provider rows in PostgreSQL.

    Input order does not change the digest. Duplicate exact provider identities
    fail rather than silently choosing a conflicting printing or overwriting it.
    """
    scope = _scope(provider, system_code, language)
    _source_url(source_url)
    _text(source_revision, "source revision", 256)
    _text(permission_ref, "permission reference", 512)
    directory, connection = _temporary_connection()
    try:
        connection.execute("create table staging (key text primary key, payload blob not null)")
        count = total = 0
        for value in rows:
            count += 1
            _require(count <= MAX_ROWS, "Catalogue row bound exceeded")
            row = _row(value, scope)
            payload = _json(row)
            total += len(payload) + 1
            _require(total <= MAX_RAW_BYTES and len(payload) + 2 <= MAX_PART_BYTES,
                     "Catalogue byte bound exceeded")
            try:
                connection.execute("insert into staging values (?, ?)", (row["key"], payload))
            except sqlite3.IntegrityError as exc:
                raise R2FirstCatalogueError("Duplicate exact catalogue identity") from exc
        _require(count > 0, "Empty catalogue cannot replace a published partition")
        parts = []
        descriptors = []
        content_hash = hashlib.sha256()
        batch, batch_keys, batch_bytes = [], [], 2

        def finish_part():
            nonlocal batch, batch_keys, batch_bytes
            raw = b"[" + b",".join(batch) + b"]"
            descriptors.append({"ordinal": len(parts), "sha256": hashlib.sha256(raw).hexdigest(),
                                "raw_bytes": len(raw), "rows": len(batch),
                                "first_key": batch_keys[0], "last_key": batch_keys[-1]})
            parts.append(raw)
            batch, batch_keys, batch_bytes = [], [], 2

        for key, payload in connection.execute("select key, payload from staging order by key"):
            addition = len(payload) + bool(batch)
            if batch and (len(batch) == MAX_PART_ROWS or batch_bytes + addition > MAX_PART_BYTES):
                finish_part()
                addition = len(payload)
            batch.append(payload)
            batch_keys.append(key)
            batch_bytes += addition
            content_hash.update(payload + b"\n")
        if batch:
            finish_part()
        manifest = {"schema": SCHEMA, "provider": provider, "system_code": system_code,
                    "language": language, "source_url": source_url,
                    "source_revision": source_revision, "permission_ref": permission_ref,
                    "record_count": count, "raw_bytes": sum(len(part) for part in parts),
                    "content_sha256": content_hash.hexdigest(), "parts": descriptors}
        return PreparedCatalogue(canonical_manifest_bytes(manifest), tuple(parts))
    finally:
        connection.close()
        directory.cleanup()


def _parse_part(raw: bytes, part: dict, scope) -> list[dict]:
    _require(type(raw) is bytes and len(raw) == part["raw_bytes"]
             and len(raw) <= MAX_PART_BYTES and hashlib.sha256(raw).hexdigest() == part["sha256"],
             "Catalogue part failed byte integrity")
    rows = _decode(raw)
    _require(type(rows) is list and len(rows) == part["rows"], "Catalogue part row count mismatch")
    previous = ""
    normalized = []
    for row in rows:
        checked = _row(row, scope, stored=True)
        _require(previous < checked["key"], "Unordered or duplicate catalogue identity")
        previous = checked["key"]
        normalized.append(checked)
    _require(rows[0]["key"] == part["first_key"] and rows[-1]["key"] == part["last_key"],
             "Catalogue part key range mismatch")
    _require(_json(normalized) == raw, "Catalogue part is not canonical closed-schema JSON")
    return normalized


def _verify_bundle(bundle: PreparedCatalogue) -> dict:
    _require(type(bundle) is PreparedCatalogue and type(bundle.parts) is tuple
             and type(bundle._manifest_bytes) is bytes
             and 0 < len(bundle._manifest_bytes) <= MAX_MANIFEST_BYTES,
             "Invalid prepared catalogue")
    manifest = validate_manifest(bundle.manifest)
    _require(bundle._manifest_bytes == canonical_manifest_bytes(manifest)
             and len(bundle.parts) == len(manifest["parts"]), "Invalid prepared catalogue parts")
    scope = tuple(manifest[field] for field in ("provider", "system_code", "language"))
    content_hash = hashlib.sha256()
    for raw, part in zip(bundle.parts, manifest["parts"], strict=True):
        for row in _parse_part(raw, part, scope):
            content_hash.update(_json(row) + b"\n")
    _require(content_hash.hexdigest() == manifest["content_sha256"], "Catalogue content digest mismatch")
    return manifest


async def _put_readback(raw: bytes, storage) -> None:
    expected = hashlib.sha256(raw).hexdigest()
    try:
        receipt = await asyncio.to_thread(storage.put_verified_reference_snapshot, raw)
        _require(type(receipt) is dict and receipt.get("verified") is True
                 and receipt.get("sha256") == expected, "Invalid R2 write receipt")
        readback = await asyncio.to_thread(storage.read_verified_reference_snapshot, expected)
        _require(type(readback) is bytes and readback == raw, "R2 readback differs from prepared bytes")
    except R2FirstCatalogueError:
        raise
    except Exception as exc:
        raise R2FirstCatalogueError("R2 catalogue upload or readback failed") from exc


async def upload_and_verify(bundle: PreparedCatalogue, storage) -> dict:
    """Upload immutable parts, then the immutable manifest; never mutate a pointer."""
    manifest = await asyncio.to_thread(_verify_bundle, bundle)
    for raw in bundle.parts:
        await _put_readback(raw, storage)
    # A failed partial upload leaves only unreferenced immutable objects. The
    # caller cannot publish a verified manifest until this final step succeeds.
    await _put_readback(bundle._manifest_bytes, storage)
    return manifest


async def load_manifest(digest: str, storage) -> dict:
    """Load the exact approved registry digest, not a user-selected URL/path."""
    _digest(digest, "manifest digest")
    try:
        raw = await asyncio.to_thread(storage.read_verified_reference_snapshot, digest)
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST_BYTES
                 and hashlib.sha256(raw).hexdigest() == digest, "Manifest failed byte integrity")
        manifest = validate_manifest(_decode(raw))
        _require(canonical_manifest_bytes(manifest) == raw, "Manifest is not canonical JSON")
        return manifest
    except R2FirstCatalogueError:
        raise
    except Exception as exc:
        raise R2FirstCatalogueError("R2 catalogue manifest unavailable") from exc


def _today(value) -> str:
    if value is None:
        return datetime.now(timezone.utc).date().isoformat()
    _require(type(value) is date, "Invalid catalogue browse date")
    return value.isoformat()


def _query_keys(value, label):
    if value is None:
        return None
    _require(type(value) in (list, tuple, set, frozenset) and len(value) <= MAX_OWNED_KEYS,
             f"Invalid or excessive {label}")
    for key in value:
        _require(type(key) is str and _KEY.fullmatch(key), f"Invalid {label}")
    return sorted(set(value))


class Snapshot:
    """One verified partition with a disposable SQLite index and no SQL fallback."""

    def __init__(self, manifest: dict):
        self._manifest = validate_manifest(manifest)
        self.manifest_digest = manifest_digest(manifest)
        self.provider = manifest["provider"]
        self.system_code = manifest["system_code"]
        self.language = manifest["language"]
        self.record_count = manifest["record_count"]
        self._directory, self._connection = _temporary_connection()
        self._lock = threading.RLock()
        self._closed = False
        self._ready = False
        self._fts = False
        try:
            self._connection.execute("""create table records (
                key text primary key, name_sort text not null, number_sort text not null,
                set_id text not null, set_name text not null, release_date text,
                product_type text not null, browse_group text not null,
                search_text text not null, payload text not null)""")
        except BaseException:
            self.close()
            raise

    @property
    def manifest(self) -> dict:
        return _decode(_json(self._manifest))

    def _append(self, rows):
        with self._lock:
            self._available(ready=False)
            values = []
            for row in rows:
                # Exact display values remain in payload. Search normalization
                # never becomes an identity key or a canonical approval.
                search = " ".join([row["name"], row["card_number"], row["set_name"],
                                   row["provider_id"], *row.get("details", {}).values()]).casefold()
                values.append((row["key"], row["name"].casefold(), row["card_number"].casefold(),
                               row["set_id"], row["set_name"], row["release_date"], row["product_type"],
                               group_for(row["system_code"], row.get("details", {})), search,
                               _json(row).decode("utf-8")))
            self._connection.executemany("insert into records values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)

    def _finish(self):
        with self._lock:
            self._available(ready=False)
            actual = self._connection.execute("select count(*) from records").fetchone()[0]
            _require(actual == self.record_count, "Runtime index row count mismatch")
            for statement in (
                "create index records_name on records(name_sort, key)",
                "create index records_number on records(number_sort, key)",
                "create index records_date on records(release_date, name_sort, key)",
                "create index records_set on records(set_id, name_sort, key)",
                "create index records_type on records(product_type, name_sort, key)",
                "create index records_group on records(browse_group, set_id, name_sort, key)",
            ):
                self._connection.execute(statement)
            # Trigram FTS accelerates 3+ character substring searches. Builds
            # without FTS5 still use the bounded on-disk index, never SQL/R2 IO
            # per item. A final instr() check preserves exact substring meaning.
            try:
                self._connection.execute("""create virtual table record_search using fts5(
                    search_text, content='records', content_rowid='rowid', tokenize='trigram')""")
            except sqlite3.OperationalError as exc:
                if "no such module" not in str(exc) and "no such tokenizer" not in str(exc):
                    raise
            else:
                self._connection.execute("insert into record_search(record_search) values ('rebuild')")
                self._fts = True
            self._connection.commit()
            self._connection.execute("pragma query_only=ON")
            self._ready = True

    def _available(self, *, ready=True):
        _require(not self._closed and (self._ready or not ready), "Catalogue snapshot is unavailable")

    def search(self, q="", set_id="", sort="name", limit=40, offset=0, *,
               include_upcoming=False, today=None, keys=None, exclude_keys=None,
               product_type="", browse_group="") -> dict:
        _text(q, "search query", 200, empty=True)
        _text(set_id, "set ID", 256, empty=True)
        _require(type(include_upcoming) is bool, "Invalid upcoming flag")
        _require(type(product_type) is str and product_type in ("", "CARD", "FIGURE"),
                 "Unsupported product type filter")
        try:
            validate_browse_group(browse_group, system_code=self.system_code)
        except ValueError as exc:
            raise R2FirstCatalogueError("Unsupported catalogue browse group") from exc
        keys = _query_keys(keys, "included catalogue keys")
        exclude_keys = _query_keys(exclude_keys, "excluded catalogue keys")
        _require(type(limit) is int and 1 <= limit <= MAX_RESULT_ROWS
                 and type(offset) is int and 0 <= offset <= MAX_ROWS, "Invalid catalogue pagination")
        orders = {"name": "r.name_sort asc, r.key asc",
                  "name_desc": "r.name_sort desc, r.key asc",
                  "number": "r.number_sort asc, r.name_sort asc, r.key asc",
                  "newest": "r.release_date is null, r.release_date desc, r.name_sort asc, r.key asc",
                  "oldest": "r.release_date is null, r.release_date asc, r.name_sort asc, r.key asc"}
        _require(type(sort) is str and sort in orders, "Unsupported catalogue sort")
        conditions, params = [], []
        if not include_upcoming:
            conditions.append("(r.release_date is null or r.release_date <= ?)")
            params.append(_today(today))
        if set_id:
            conditions.append("r.set_id = ?")
            params.append(set_id)
        if product_type:
            conditions.append("r.product_type = ?")
            params.append(product_type)
        if browse_group:
            conditions.append("r.browse_group = ?")
            params.append(browse_group)
        if keys is not None:
            # Keys are an ephemeral, caller-authorised overlay. They are never
            # written into catalogue files or the disposable source index.
            conditions.append("r.key in (select value from json_each(?))")
            params.append(_json(keys).decode("utf-8"))
        if exclude_keys:
            conditions.append("r.key not in (select value from json_each(?))")
            params.append(_json(exclude_keys).decode("utf-8"))
        folded = q.casefold()
        if folded:
            conditions.append("instr(r.search_text, ?) > 0")
            params.append(folded)
            if self._fts and len(folded) >= 3:
                conditions.append("r.rowid in (select rowid from record_search where record_search match ?)")
                params.append('"' + folded.replace('"', '""') + '"')
        where = " where " + " and ".join(conditions) if conditions else ""
        with self._lock:
            self._available()
            total = self._connection.execute("select count(*) from records r" + where, params).fetchone()[0]
            found = self._connection.execute("select payload from records r" + where
                                             + " order by " + orders[sort] + " limit ? offset ?",
                                             [*params, limit, offset]).fetchall()
        return {"items": [_decode(row[0].encode("utf-8")) for row in found],
                "total": total, "limit": limit, "offset": offset}

    def get(self, key: str) -> dict | None:
        _require(type(key) is str and _KEY.fullmatch(key), "Invalid catalogue key")
        with self._lock:
            self._available()
            found = self._connection.execute("select payload from records where key = ?", (key,)).fetchone()
        return _decode(found[0].encode("utf-8")) if found else None

    def sets(self, *, include_upcoming=False, today=None, browse_group="") -> list[dict]:
        _require(type(include_upcoming) is bool, "Invalid upcoming flag")
        try:
            validate_browse_group(browse_group, system_code=self.system_code)
        except ValueError as exc:
            raise R2FirstCatalogueError("Unsupported catalogue browse group") from exc
        conditions, params = [], []
        if not include_upcoming:
            conditions.append("(release_date is null or release_date <= ?)")
            params.append(_today(today))
        if browse_group:
            conditions.append("browse_group = ?")
            params.append(browse_group)
        where = " where " + " and ".join(conditions) if conditions else ""
        with self._lock:
            self._available()
            rows = self._connection.execute("select set_id, set_name, count(*) from records"
                                            + where + " group by set_id, set_name order by set_name, set_id",
                                            params).fetchall()
        return [{"set_id": row[0], "set_name": row[1], "count": row[2]} for row in rows]

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._connection.close()
                self._directory.cleanup()

    def __enter__(self):
        self._available()
        return self

    def __exit__(self, *exc):
        self.close()


async def load_catalogue(manifest: dict, storage) -> Snapshot:
    """Build one all-or-nothing index. The caller retains its last good pointer."""
    manifest = validate_manifest(manifest)
    scope = tuple(manifest[field] for field in ("provider", "system_code", "language"))
    # Construct synchronously so cancellation cannot lose the only reference
    # to a just-created temporary index. This creates an empty local file only;
    # all downloads, data inserts and expensive index builds run off-loop.
    snapshot = Snapshot(manifest)
    content_hash = hashlib.sha256()
    try:
        for part in manifest["parts"]:
            raw = await asyncio.to_thread(storage.read_verified_reference_snapshot, part["sha256"])
            rows = await asyncio.to_thread(_parse_part, raw, part, scope)
            for row in rows:
                content_hash.update(_json(row) + b"\n")
            await asyncio.to_thread(snapshot._append, rows)
        _require(content_hash.hexdigest() == manifest["content_sha256"], "Catalogue content digest mismatch")
        await asyncio.to_thread(snapshot._finish)
        return snapshot
    except BaseException as exc:
        # A cancelled to_thread() can still finish its SQLite work. The close
        # holds the same lock and must not block the event loop while waiting.
        await asyncio.shield(asyncio.to_thread(snapshot.close))
        if isinstance(exc, R2FirstCatalogueError) or not isinstance(exc, Exception):
            raise
        raise R2FirstCatalogueError("R2 catalogue index unavailable") from exc
