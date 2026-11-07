"""D1-only shadow catalogue projection from checksum-verified R2 identities.

Stage A: no production connection, prices, ownership, Shopify, auth or ledgers.
Rows are from an already verified r2_first_catalogue.Snapshot; the source
manifest digest and original stable key survive projection unchanged.
A partially staged generation can never appear in the active read view.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterable

from . import r2_first_catalogue as r2

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SQLITE_COLUMNS = (
    "manifest_sha", "card_key", "provider", "system_code", "language",
    "provider_id", "product_type", "name", "name_fold", "set_id", "set_name",
    "card_number", "rarity", "finish", "release_date", "cardmarket_product_id",
)
MAX_SOURCE_ROWS = r2.MAX_ROWS
MAX_BOUND_PARAMETERS = 100
MAX_BATCH_STATEMENTS = 12
ROW_WIDTH = len(SQLITE_COLUMNS)

# No monetary column. Source guides must never be auto-published as Market Value.
SCHEMA = """
create table if not exists shadow_generations (
 manifest_sha text primary key check(length(manifest_sha)=64),
 provider text not null, system_code text not null, language text not null,
 expected_rows integer not null check(expected_rows between 1 and 250000),
 projection_sha text not null check(length(projection_sha)=64),
 source_content_sha text not null check(length(source_content_sha)=64),
 source_revision text not null
);
create table if not exists shadow_cards (
 manifest_sha text not null references shadow_generations(manifest_sha),
 card_key text not null, provider text not null, system_code text not null,
 language text not null, provider_id text not null, product_type text not null,
 name text not null, name_fold text not null, set_id text not null,
 set_name text not null, card_number text not null, rarity text,
 finish text, release_date text, cardmarket_product_id text,
 primary key(manifest_sha,card_key),
 unique(manifest_sha,provider,system_code,language,provider_id)
);
create index if not exists shadow_cards_set_page_idx
 on shadow_cards(manifest_sha,provider,system_code,language,set_id,card_key);
create index if not exists shadow_cards_name_idx
 on shadow_cards(manifest_sha,system_code,language,name_fold,card_key);
create table if not exists shadow_active_partitions (
 provider text not null, system_code text not null, language text not null,
 manifest_sha text not null references shadow_generations(manifest_sha),
 primary key(provider,system_code,language)
);
create view if not exists shadow_live_cards as
 select c.* from shadow_cards c
 join shadow_active_partitions a
 on (a.provider,a.system_code,a.language,a.manifest_sha)
   = (c.provider,c.system_code,c.language,c.manifest_sha);
"""

# Activation is one SQL statement. Incomplete source rows cannot flip the
# pointer, even if a process crashes between REST requests or a batch fails.
ACTIVATE_SQL = """
insert into shadow_active_partitions(provider,system_code,language,manifest_sha)
select g.provider,g.system_code,g.language,g.manifest_sha
from shadow_generations g
where g.manifest_sha=?
  and (select count(*) from shadow_cards r where r.manifest_sha=g.manifest_sha)
       =g.expected_rows
on conflict(provider,system_code,language)
do update set manifest_sha=excluded.manifest_sha
"""

INSERT_GENERATION_SQL = """insert into shadow_generations
(manifest_sha,provider,system_code,language,expected_rows,projection_sha,
 source_content_sha,source_revision) values(?,?,?,?,?,?,?,?)"""

INSERT_CARD_SQL = "insert into shadow_cards (" + ",".join(SQLITE_COLUMNS) + ") values "

LIVE_CARD_SQL = """select card_key,provider_id,name,finish
from shadow_live_cards where provider=? and system_code=? and language=?
order by card_key limit ? offset ?"""

@dataclass(frozen=True)
class Projection:
    manifest_sha: str
    scope: tuple[str, str, str]
    expected_rows: int
    source_content_sha: str
    source_revision: str
    projection_sha: str
    rows: tuple[tuple, ...]

    def generation_params(self) -> tuple:
        return (self.manifest_sha, *self.scope, self.expected_rows,
                self.projection_sha, self.source_content_sha, self.source_revision)


class ProjectionError(ValueError):
    """Wrong, incomplete or unverified catalogue partition; no D1 write allowed."""


def _canonical_row(row: object, scope: tuple[str, str, str], manifest_sha: str) -> tuple:
    try:
        checked = r2._row(row, scope, stored=True)
    except (ValueError, TypeError, KeyError) as exc:
        raise ProjectionError("Invalid R2 source card identity") from exc
    details = checked.get("details") or {}
    mcm = details.get("cardmarket_product_id")
    if mcm is not None:
        if (type(mcm) is not str or not mcm.isascii() or not
                re.fullmatch(r"[1-9][0-9]{0,9}", mcm) or int(mcm) > 2**31-1):
            raise ProjectionError("Invalid original Cardmarket product identifier")
    folded = checked["name"].casefold()
    return (
        manifest_sha, checked["key"], checked["provider"],
        checked["system_code"], checked["language"], checked["provider_id"],
        checked["product_type"], checked["name"], folded, checked["set_id"],
        checked["set_name"], checked["card_number"], checked["rarity"],
        checked["finish"], checked["release_date"], mcm,
    )


def from_verified_snapshot(snapshot: r2.Snapshot) -> Projection:
    """Validate a complete, already-restored R2 snapshot before any D1 upload."""
    if not isinstance(snapshot, r2.Snapshot):
        raise ProjectionError("Only an existing verified R2 Snapshot is accepted")
    manifest = snapshot.manifest
    checksum = r2.manifest_digest(manifest)
    if (not SHA256.fullmatch(checksum) or checksum != snapshot.manifest_digest
            or snapshot.record_count != manifest["record_count"]
            or snapshot.record_count < 1 or snapshot.record_count > MAX_SOURCE_ROWS):
        raise ProjectionError("Unverified R2 catalogue generation")
    scope = tuple(manifest[x] for x in ("provider", "system_code", "language"))
    records: list[tuple] = []
    keys = set()
    offset = 0
    while offset < snapshot.record_count:
        page_size = min(100, snapshot.record_count - offset)
        page = snapshot.search(limit=page_size, offset=offset, include_upcoming=True)
        if (page.get("total") != snapshot.record_count
                or not isinstance(page.get("items"), list)
                or len(page["items"]) != page_size):
            raise ProjectionError("Incomplete R2 pagination")
        for row in page["items"]:
            canonical = _canonical_row(row, scope, checksum)
            if canonical[1] in keys:
                raise ProjectionError("Duplicate R2 stable identity")
            keys.add(canonical[1])
            records.append(canonical)
        offset += page_size
    if len(records) != snapshot.record_count:
        raise ProjectionError("Truncated catalogue source")
    # The digest is order-independent of R2 name-sort pagination; D1 can
    # independently recalculate this digest with indexed card_key pages.
    cumulative = hashlib.sha256()
    for record in sorted(records, key=lambda value: value[1]):
        cumulative.update(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
    return Projection(checksum, scope, snapshot.record_count,
                      manifest["content_sha256"], manifest["source_revision"],
                      cumulative.hexdigest(), tuple(records))


def insert_statements(projection: Projection) -> Iterable[dict]:
    """Prepared SQL with at most 100 binds; original values are never SQL text."""
    if not isinstance(projection, Projection):
        raise ProjectionError("Unverified shadow projection")
    chunk_size = MAX_BOUND_PARAMETERS // ROW_WIDTH
    for start in range(0, projection.expected_rows, chunk_size):
        chunk = projection.rows[start:start + chunk_size]
        if not chunk or len(chunk) * ROW_WIDTH > MAX_BOUND_PARAMETERS:
            raise ProjectionError("Invalid D1 insert chunk")
        values = ",".join("(" + ",".join("?" for _ in range(ROW_WIDTH)) + ")" for _ in chunk)
        yield {"sql": INSERT_CARD_SQL + values,
               "params": [part for row in chunk for part in row]}


def generation_statement(projection: Projection) -> dict:
    return {"sql": INSERT_GENERATION_SQL, "params": list(projection.generation_params())}


def activation_statement(projection: Projection) -> dict:
    return {"sql": ACTIVATE_SQL, "params": [projection.manifest_sha]}
