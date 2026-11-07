"""Disk-backed, resumable comic and manga imports; no inventory/media writes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from uuid import UUID

from .book_catalogue_sources import (IMPORT_VERSION, ReviewRequired, canonical_json,
                                    normalise, validate_entry, barcode_aliases)
from .database_capacity import FREE_DATABASE_LIMIT_BYTES, REFRESH_PAUSE_BYTES, check_database_capacity

MAX_LINE_BYTES = 2_000_000
MAX_BATCH = 100


class ImportPaused(RuntimeError):
    pass


def open_stage(path):
    state = sqlite3.connect(path)
    state.row_factory = sqlite3.Row
    state.executescript("""create table if not exists metadata(key text primary key,value text not null);
        create table if not exists records(line integer primary key, source_key text, identity_key text,
          status text not null, reason text, entry text not null, catalogue_id text, cover_attempted integer not null default 0);
        create index if not exists records_source on records(source_key);
        create index if not exists records_status on records(status,line);""")
    return state


def stage_file(state, path, provider):
    """Stage an immutable JSONL snapshot with bounded memory and checkpoints."""
    with Path(path).open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    binding = canonical_json(dict(input_sha256=sha, provider=provider, version=IMPORT_VERSION))
    existing = state.execute("select value from metadata where key='binding'").fetchone()
    if existing and existing[0] != binding:
        raise ImportPaused("STAGE_INPUT_CHANGED_USE_NEW_STATE")
    state.execute("insert or ignore into metadata values('binding',?)", (binding,))
    checkpoint = state.execute("select value from metadata where key='last_line'").fetchone()
    last = int(checkpoint[0]) if checkpoint else 0
    state.commit()
    with Path(path).open("rb") as stream:
        line_number = 0
        while raw := stream.readline(MAX_LINE_BYTES + 1):
            line_number += 1
            if len(raw) > MAX_LINE_BYTES:
                raise ImportPaused("INPUT_LINE_TOO_LARGE")
            if line_number <= last:
                continue
            entry, source_key, reason, status = {}, None, None, "READY"
            try:
                entry = normalise(provider, json.loads(raw))
                source_key = entry["provider"] + ":" + entry["record_id"]
                prior = state.execute("select entry,status from records where source_key=? order by line limit 1", (source_key,)).fetchone()
                if prior:
                    if json.loads(prior["entry"])["record_digest"] == entry["record_digest"] and prior["status"] != "REVIEW":
                        status, reason = "DUPLICATE", "DUPLICATE_SOURCE_RECORD"
                    else:
                        status, reason = "REVIEW", "CONFLICTING_SOURCE_RECORDS"
                        state.execute("update records set status='REVIEW',reason=? where source_key=?", (reason, source_key))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                status = "REVIEW"
                reason = str(exc) if isinstance(exc, ReviewRequired) else "INVALID_PROVIDER_RECORD"
            state.execute("insert into records(line,source_key,identity_key,status,reason,entry) values(?,?,?,?,?,?)",
                          (line_number, source_key, entry.get("identity_key"), status, reason, canonical_json(entry)))
            state.execute("insert or replace into metadata values('last_line',?)", (str(line_number),))
            if line_number % 200 == 0:
                state.commit()
    state.execute("insert or replace into metadata values('complete','true')")
    state.commit()
    return stage_report(state)


def estimated_bytes(entries):
    # Planning reserve for two provenance JSONB copies, product/mapping rows,
    # indexes and page overhead; not a storage quotation or a measured promise.
    return sum(8192 + 4 * len(canonical_json(entry).encode()) for entry in entries)


def stage_report(state):
    counts = dict(state.execute("select status,count(*) from records group by status").fetchall())
    reasons = dict(state.execute("select reason,count(*) from records where reason is not null group by reason").fetchall())
    systems, artwork, reserve = Counter(), Counter(), 0
    for row in state.execute("select entry from records where status='READY'"):
        entry = json.loads(row[0])
        systems[entry["book"]["system_code"]] += 1
        artwork["checked" if entry.get("reference") else "pending" if entry.get("image_url") else "unavailable"] += 1
        reserve += estimated_bytes([entry])
    return dict(version=IMPORT_VERSION, statuses=counts, review_reasons=reasons,
                ready_by_system=dict(systems), artwork=dict(artwork),
                estimated_database_bytes=reserve, pause_threshold_bytes=REFRESH_PAUSE_BYTES,
                complete=bool(state.execute("select 1 from metadata where key='complete'").fetchone()))


async def import_capacity(connection, database_limit_bytes=FREE_DATABASE_LIMIT_BYTES):
    """Default to today's quota; a larger, verified quota is explicit per job.

    Storage upgrades do not automatically change other catalogue jobs' guards.
    Retain at least 20% / 100 MB headroom for inventory, indexes and audit growth.
    """
    if type(database_limit_bytes) is not int or not FREE_DATABASE_LIMIT_BYTES <= database_limit_bytes <= 10**15:
        raise ValueError("Verified database quota required in decimal bytes")
    capacity = await check_database_capacity(connection)
    threshold = database_limit_bytes - max(100_000_000, database_limit_bytes // 5)
    readonly = capacity.reason == "DATABASE_READ_ONLY"
    allowed = not readonly and capacity.database_bytes < threshold
    return dict(database_bytes=capacity.database_bytes, database_limit_bytes=database_limit_bytes,
                pause_threshold_bytes=threshold, refresh_allowed=allowed,
                reason="DATABASE_READ_ONLY" if readonly else "WITHIN_SAFE_BULK_REFRESH_CAPACITY" if allowed else "BULK_REFRESH_DEFERRED_CAPACITY")


async def capacity_plan(connection, state, database_limit_bytes=FREE_DATABASE_LIMIT_BYTES):
    report = stage_report(state)
    capacity = await import_capacity(connection, database_limit_bytes)
    report["capacity"] = capacity
    report["pause_threshold_bytes"] = capacity["pause_threshold_bytes"]
    report["whole_stage_fits_reserve"] = capacity["refresh_allowed"] and capacity["database_bytes"] + report["estimated_database_bytes"] < capacity["pause_threshold_bytes"]
    return report


def source_attributes(entry, batch):
    return dict(publisher=entry["book"]["publisher"], book_format=entry["book"]["book_format"],
                identity_source={"GCD":"GCD_CATALOGUE", "OPEN_LIBRARY":"OPEN_LIBRARY_CATALOGUE"}.get(entry["provider"],"OFFICIAL_PUBLISHER_CATALOGUE"),
                source_url=entry["source_url"], source_checked_at=entry["observed_on"],
                cover_rights_status="PENDING", publisher_reference=entry["reference"],
                catalogue_import=dict(version=IMPORT_VERSION, batch=batch, provider=entry["provider"],
                                      record_id=entry["record_id"], record_digest=entry["record_digest"],
                                      metadata_license=entry["metadata_license"],
                                      attribution="Adapted from the Grand Comics Database" if entry["provider"] == "GCD" else "Edition metadata from Open Library" if entry["provider"] == "OPEN_LIBRARY" else None,
                                      source_snapshot=entry.get("evidence_url") if entry["provider"] == "OPEN_LIBRARY" else None))


def _object(value):
    return json.loads(value) if isinstance(value, str) else value


async def _apply_one(connection, entry, batch):
    validate_entry(entry)
    prior = await connection.fetchrow("""select catalogue_id,metadata from tcg.provider_catalogue_mappings
        where source_provider=$1 and provider_entity_type='COMIC_PRINTING' and provider_id=$2
          and provider_variant_key='' and provider_language=''""", entry["provider"], entry["record_id"])
    if prior:
        if (_object(prior["metadata"]) or {}).get("record_digest") == entry["record_digest"]:
            return "EXISTING", str(prior["catalogue_id"]), None
        return "REVIEW", None, "SOURCE_CHANGED_REVIEW_REQUIRED"
    book, product = entry["book"], entry["catalogue"]
    existing = await connection.fetchrow("""select p.id,to_jsonb(p)-array['id','identity_key','created_at'] as product,
          (to_jsonb(b)-array['catalogue_id','identity_status','attributes','version','created_at','updated_at'])
            ||jsonb_build_object('publisher',b.attributes->>'publisher','book_format',b.attributes->>'book_format') as book
        from tcg.catalogue_products p left join tcg.comic_printing_details b on b.catalogue_id=p.id
        where p.identity_key=$1""", entry["identity_key"])
    if existing and (_object(existing["book"]) != book or _object(existing["product"]) != product):
        return "REVIEW", None, "EXISTING_IDENTITY_CONFLICT"
    if not existing and book.get("barcode_gtin"):
        collisions = await connection.fetch("""select b.cover_code,b.printing_number,b.series_title,b.issue_number,b.system_code
            from tcg.comic_printing_details b join tcg.catalogue_products p on p.id=b.catalogue_id
            where b.barcode_gtin=any($1::text[]) and ($2::text is null or p.language=$2)""",
            barcode_aliases(book["barcode_gtin"]), None if entry["provider"]=="OPEN_LIBRARY" else product["language"])
        for collision in collisions:
            # Documented variants/reprints may share an ISBN. An unknown printing
            # or a changed title/issue under the same barcode needs human review.
            distinct = any(book[k] is not None and collision[k] is not None and book[k] != collision[k]
                           for k in ("cover_code", "printing_number"))
            same_issue = all(book[k] == collision[k] for k in ("series_title", "issue_number", "system_code"))
            if not (distinct and same_issue):
                return "REVIEW", None, "BARCODE_IDENTITY_CONFLICT"
    catalogue_id = existing["id"] if existing else UUID(entry["id"])
    if not existing:
        attrs = canonical_json(source_attributes(entry, batch))
        await connection.execute("""insert into tcg.catalogue_products
            (id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
            values($1,$2,'COMIC',$3,$4,$5,$6,$7,$8,$9)""", catalogue_id, entry["identity_key"],
            product["game"], product["name"], product["set_name"], product["card_number"], product["variant"], product["rarity"], product["language"])
        await connection.execute("""insert into tcg.catalogue_product_profiles
            (catalogue_id,system_code,collectible_type,identity_status,release_date,attributes)
            values($1,$2,'COMIC','STRUCTURED',$3,$4::jsonb)""", catalogue_id, book["system_code"],
            date.fromisoformat(entry["release_date"]) if entry["release_date"] else None, attrs)
        await connection.execute("""insert into tcg.comic_printing_details
            (catalogue_id,system_code,series_title,volume_identifier,issue_number,printing_number,
             release_year,cover_code,cover_artist,barcode_gtin,identity_status,attributes)
            values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'STRUCTURED',$11::jsonb)""", catalogue_id,
            *[book[k] for k in ("system_code", "series_title", "volume_identifier", "issue_number", "printing_number",
                               "release_year", "cover_code", "cover_artist", "barcode_gtin")], attrs)
    await connection.execute("""insert into tcg.provider_catalogue_mappings
        (catalogue_id,system_code,source_provider,provider_entity_type,provider_id,
         provider_variant_key,provider_language,source_reference,match_status,verification_basis,confidence,metadata)
        values($1,$2,$3,'COMIC_PRINTING',$4,'','',$5,'REVIEW','DETERMINISTIC_EXACT',0,$6::jsonb)""",
        catalogue_id, book["system_code"], entry["provider"], entry["record_id"], entry["source_url"],
        canonical_json(dict(import_version=IMPORT_VERSION, record_digest=entry["record_digest"],
                            batch=batch, observed_on=entry["observed_on"], metadata_license=entry["metadata_license"],
                            identity_key=entry["identity_key"])))
    return "EXISTING" if existing else "IMPORTED", str(catalogue_id), None


async def apply_batch(connection, entries, batch, database_limit_bytes=FREE_DATABASE_LIMIT_BYTES):
    """A chunk either commits fully or leaves its checkpoint ready for replay."""
    if not 1 <= len(entries) <= MAX_BATCH:
        raise ValueError("A batch must have 1–100 records")
    for entry in entries:
        validate_entry(entry)
    async with connection.transaction():
        await connection.execute("set local lock_timeout='5s'")
        await connection.execute("set local statement_timeout='30s'")
        # Share the starter import lock; canonical product uniqueness also guards
        # races with manual intake. Retry an aborted batch without advancing it.
        await connection.execute("select pg_advisory_xact_lock(hashtext('publisher-book-catalogue-starter'))")
        capacity = await import_capacity(connection, database_limit_bytes)
        if not capacity["refresh_allowed"]:
            raise ImportPaused(capacity["reason"])
        if capacity["database_bytes"] + estimated_bytes(entries) >= capacity["pause_threshold_bytes"]:
            raise ImportPaused("BATCH_EXCEEDS_CAPACITY_RESERVE")
        results = [await _apply_one(connection, entry, batch) for entry in entries]
    return results


async def apply_stage(connection, state, *, batch_size=50, max_batches=20, database_limit_bytes=FREE_DATABASE_LIMIT_BYTES):
    if not 1 <= batch_size <= MAX_BATCH or not 1 <= max_batches <= 1000:
        raise ValueError("Bounded batch size/count required")
    if not state.execute("select 1 from metadata where key='complete'").fetchone():
        raise ImportPaused("STAGING_NOT_COMPLETE")
    binding = state.execute("select value from metadata where key='binding'").fetchone()[0]
    batch = json.loads(binding)["input_sha256"]
    for _ in range(max_batches):
        rows = state.execute("select line,entry from records where status='READY' order by line limit ?", (batch_size,)).fetchall()
        if not rows:
            break
        results = await apply_batch(connection, [json.loads(r["entry"]) for r in rows], batch, database_limit_bytes)
        # If the process dies after the Postgres commit, the source mapping makes
        # the repeated chunk EXISTING; no distributed transaction is required.
        with state:
            state.executemany("update records set status=?,catalogue_id=?,reason=? where line=?",
                              [(*result, row["line"]) for row, result in zip(rows, results)])
    return stage_report(state)

