"""Reviewable bounded SQL batches for an authorised database connector.

This is an offline exporter, not an HTTP/admin endpoint. It creates no permanent
SQL function, grants or elevated role. The fixed transaction reproduces the book
importer's identity, barcode, source-digest and capacity checks. Source fields
are one hash-bound JSON payload, never SQL expressions or identifiers.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re

from .book_bulk_import import ImportPaused, estimated_bytes, source_attributes
from .book_catalogue_sources import (IMPORT_VERSION, barcode_aliases, canonical_json,
                                     validate_entry)


def _literal(text):
    """A data-only PostgreSQL dollar string; delimiter cannot occur in input."""
    digest = hashlib.sha256(text.encode()).hexdigest()
    delimiter = "$book_payload_" + digest + "$"
    if delimiter in text:
        raise ImportPaused("BOOK_SQL_PAYLOAD_DELIMITER_CONFLICT")
    return delimiter + text + delimiter


SQL_BODY = """
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $book_guard$
begin
  if current_setting('default_transaction_read_only') <> 'off'
     or current_setting('transaction_read_only') <> 'off' then
    raise exception 'DATABASE_READ_ONLY';
  end if;
end $book_guard$;
select pg_advisory_xact_lock(hashtext('publisher-book-catalogue-starter'));
create temporary table book_connector_receipt (
  line integer primary key, source_id text not null, status text not null,
  catalogue_id uuid, reason text, record_digest text not null
) on commit drop;
do $book_apply$
declare
  payload_text text := convert_from(decode('__PAYLOAD_BASE64__','base64'),'UTF8');
  payload jsonb;
  r record;
  prior record;
  existing record;
  e jsonb;
  b jsonb;
  p jsonb;
  cid uuid;
  current_bytes bigint;
  estimated_bytes bigint;
  had_existing boolean;
  isbn_conflict boolean;
begin
  if encode(sha256(convert_to(payload_text,'UTF8')),'hex') <> '__PAYLOAD_SHA__' then
    raise exception 'BOOK_CONNECTOR_PAYLOAD_HASH_MISMATCH';
  end if;
  payload := payload_text::jsonb;
  if jsonb_typeof(payload) <> 'array' or jsonb_array_length(payload) not between 1 and 100 then
    raise exception 'BOOK_CONNECTOR_BATCH_BOUNDS';
  end if;
  select sum(x.estimated_bytes) into estimated_bytes from jsonb_to_recordset(payload)
    as x(estimated_bytes bigint);
  select pg_database_size(current_database()) into current_bytes;
  if current_bytes < 0 or estimated_bytes is null or estimated_bytes <= 0
     or current_bytes + estimated_bytes >= 400000000 then
    raise exception 'BATCH_EXCEEDS_CAPACITY_RESERVE';
  end if;
  for r in select * from jsonb_to_recordset(payload)
    as x(line integer, entry jsonb, attributes jsonb, aliases jsonb,
         mapping_metadata jsonb, estimated_bytes bigint)
    order by line
  loop
    e := r.entry; b := e->'book'; p := e->'catalogue';
    if e->>'provider' <> 'OPEN_LIBRARY' or e->>'import_version' <> 'book-bulk-v1'
       or e->>'record_id' !~ '^OL[1-9][0-9]*M$'
       or e->>'source_url' <> 'https://openlibrary.org/books/' || (e->>'record_id')
       or e->>'record_digest' !~ '^[a-f0-9]{64}$'
       or e->>'image_url' is not null or e->>'reference' is not null
       or b->>'printing_number' is not null or b->>'cover_code' is not null
       or b->>'cover_artist' is not null then
      raise exception 'BOOK_CONNECTOR_SOURCE_INTEGRITY';
    end if;
    select m.catalogue_id,m.metadata into prior from tcg.provider_catalogue_mappings m
      where m.source_provider=e->>'provider' and m.provider_entity_type='COMIC_PRINTING'
        and m.provider_id=e->>'record_id' and m.provider_variant_key='' and m.provider_language='';
    if found then
      if prior.metadata->>'record_digest'=e->>'record_digest' then
        insert into book_connector_receipt values(r.line,e->>'record_id','EXISTING',prior.catalogue_id,null,e->>'record_digest');
      else
        insert into book_connector_receipt values(r.line,e->>'record_id','REVIEW',null,'SOURCE_CHANGED_REVIEW_REQUIRED',e->>'record_digest');
      end if;
      continue;
    end if;
    select cp.id,to_jsonb(cp)-array['id','identity_key','created_at'] as product,
      (to_jsonb(cd)-array['catalogue_id','identity_status','attributes','version','created_at','updated_at'])
       || jsonb_build_object('publisher',cd.attributes->>'publisher','book_format',cd.attributes->>'book_format') as book
      into existing from tcg.catalogue_products cp
      left join tcg.comic_printing_details cd on cd.catalogue_id=cp.id
      where cp.identity_key=e->>'identity_key';
    had_existing := found;
    if had_existing and (existing.book is distinct from b or existing.product is distinct from p) then
      insert into book_connector_receipt values(r.line,e->>'record_id','REVIEW',null,'EXISTING_IDENTITY_CONFLICT',e->>'record_digest');
      continue;
    end if;
    if not had_existing and b->>'barcode_gtin' is not null then
      select exists(select 1 from tcg.comic_printing_details cd
        join tcg.catalogue_products cp on cp.id=cd.catalogue_id
        where cd.barcode_gtin in(select jsonb_array_elements_text(r.aliases))) into isbn_conflict;
      -- OPEN_LIBRARY never supplies printing/cover variants, so every existing
      -- barcode alias across every language is held, just like _apply_one.
      if isbn_conflict then
        insert into book_connector_receipt values(r.line,e->>'record_id','REVIEW',null,'BARCODE_IDENTITY_CONFLICT',e->>'record_digest');
        continue;
      end if;
    end if;
    cid := case when had_existing then existing.id else (e->>'id')::uuid end;
    if not had_existing then
      insert into tcg.catalogue_products
        (id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
      values(cid,e->>'identity_key','COMIC',p->>'game',p->>'name',p->>'set_name',
        p->>'card_number',p->>'variant',p->>'rarity',p->>'language');
      insert into tcg.catalogue_product_profiles
        (catalogue_id,system_code,collectible_type,identity_status,release_date,attributes)
      values(cid,b->>'system_code','COMIC','STRUCTURED',(e->>'release_date')::date,r.attributes);
      insert into tcg.comic_printing_details
        (catalogue_id,system_code,series_title,volume_identifier,issue_number,printing_number,
         release_year,cover_code,cover_artist,barcode_gtin,identity_status,attributes)
      values(cid,b->>'system_code',b->>'series_title',b->>'volume_identifier',b->>'issue_number',null,
        (b->>'release_year')::integer,null,null,b->>'barcode_gtin','STRUCTURED',r.attributes);
    end if;
    insert into tcg.provider_catalogue_mappings
      (catalogue_id,system_code,source_provider,provider_entity_type,provider_id,
       provider_variant_key,provider_language,source_reference,match_status,verification_basis,confidence,metadata)
    values(cid,b->>'system_code',e->>'provider','COMIC_PRINTING',e->>'record_id','',
      '',e->>'source_url','REVIEW','DETERMINISTIC_EXACT',0,r.mapping_metadata);
    insert into book_connector_receipt values(r.line,e->>'record_id',
      case when had_existing then 'EXISTING' else 'IMPORTED' end,cid,null,e->>'record_digest');
  end loop;
  if (select count(*) from book_connector_receipt) <> jsonb_array_length(payload) then
    raise exception 'BOOK_CONNECTOR_RECEIPT_INCOMPLETE';
  end if;
  if pg_database_size(current_database()) >= 400000000 then
    raise exception 'BULK_REFRESH_DEFERRED_CAPACITY';
  end if;
end $book_apply$;
select jsonb_build_object('snapshot_sha256','__SNAPSHOT_SHA__','payload_sha256','__PAYLOAD_SHA__',
  'batch','__BATCH__','database_bytes',pg_database_size(current_database()),
  'statuses',(select jsonb_object_agg(status,n) from
    (select status,count(*) as n from book_connector_receipt group by status) totals),
  'records',(select jsonb_agg(to_jsonb(r) order by line) from book_connector_receipt r)) as receipt;
commit;
"""


def build_batch(entries, *, snapshot_sha256, start_line=1):
    if not re.fullmatch(r"[a-f0-9]{64}", snapshot_sha256):
        raise ImportPaused("BOOK_CONNECTOR_SNAPSHOT_HASH_REQUIRED")
    if not 1 <= len(entries) <= 100 or type(start_line) is not int or start_line < 1:
        raise ImportPaused("BOOK_CONNECTOR_BATCH_BOUNDS")
    from .book_openlibrary_bulk import reviewed_hold_registry, reviewed_identity_hold
    reviewed, _ = reviewed_hold_registry()
    for entry in entries:
        validate_entry(entry)
        if entry["provider"] != "OPEN_LIBRARY":
            raise ImportPaused("BOOK_CONNECTOR_OPEN_LIBRARY_ONLY")
        if reviewed_identity_hold(isbn=entry["book"]["barcode_gtin"],
                                  source_id=entry["record_id"], reviewed=reviewed):
            raise ImportPaused("BOOK_CONNECTOR_REVIEWED_IDENTITY_HOLD")
    if len({e["record_id"] for e in entries}) != len(entries):
        raise ImportPaused("BOOK_CONNECTOR_DUPLICATE_SOURCE")
    batch = f"ol-monthly-{snapshot_sha256[:20]}-{start_line:06d}-{start_line+len(entries)-1:06d}"
    rows = [{"line": start_line+i, "entry": entry,
             "attributes": source_attributes(entry, batch),
             "aliases": barcode_aliases(entry["book"]["barcode_gtin"]),
             "mapping_metadata": dict(import_version=IMPORT_VERSION, record_digest=entry["record_digest"],
                 batch=batch, observed_on=entry["observed_on"], metadata_license=entry["metadata_license"],
                 identity_key=entry["identity_key"]),
             "estimated_bytes": estimated_bytes([entry])} for i, entry in enumerate(entries)]
    payload = canonical_json(rows)
    payload_sha = hashlib.sha256(payload.encode()).hexdigest()
    sql = SQL_BODY.replace("__PAYLOAD_SHA__", payload_sha)
    sql = sql.replace("__SNAPSHOT_SHA__", snapshot_sha256).replace("__BATCH__", batch)
    # Base64 contains no quotes or dollar signs. In particular an untrusted
    # title cannot terminate the outer DO $book_apply$ body before PL/pgSQL
    # reaches an otherwise safely dollar-quoted inner data literal.
    sql = sql.replace("__PAYLOAD_BASE64__", base64.b64encode(payload.encode()).decode("ascii"))
    expected = [{"source_id": e["record_id"], "record_digest": e["record_digest"]} for e in entries]
    readback = """with expected as (select * from jsonb_to_recordset(__EXPECTED__::jsonb)
      as x(source_id text,record_digest text))
    select jsonb_build_object('batch','__BATCH__','expected',count(*),
      'matching_source_digests',count(*) filter(where m.metadata->>'record_digest'=e.record_digest),
      'missing',count(*) filter(where m.id is null),
      'conflicting_source_digests',count(*) filter(where m.id is not null and
        m.metadata->>'record_digest' is distinct from e.record_digest),
      'new_structured',count(*) filter(where m.metadata->>'batch'='__BATCH__' and
        b.identity_status='STRUCTURED' and cp.identity_status='STRUCTURED'),
      'new_with_invented_printing',count(*) filter(where m.metadata->>'batch'='__BATCH__' and
        (b.printing_number is not null or b.cover_code is not null or b.cover_artist is not null)),
      'database_bytes',pg_database_size(current_database())) as readback
    from expected e left join tcg.provider_catalogue_mappings m
      on m.source_provider='OPEN_LIBRARY' and m.provider_entity_type='COMIC_PRINTING'
      and m.provider_id=e.source_id and m.provider_variant_key='' and m.provider_language=''
    left join tcg.comic_printing_details b on b.catalogue_id=m.catalogue_id
    left join tcg.catalogue_product_profiles cp on cp.catalogue_id=m.catalogue_id;\n"""
    readback = readback.replace("__EXPECTED__", _literal(canonical_json(expected))).replace("__BATCH__", batch)
    receipt = dict(batch=batch, snapshot_sha256=snapshot_sha256, payload_sha256=payload_sha,
                   records=len(entries), estimated_database_bytes=estimated_bytes(entries),
                   source_ids=[e["record_id"] for e in entries],
                   sql_sha256=hashlib.sha256(sql.encode()).hexdigest())
    return sql, readback, receipt


def export_stage_batches(state, directory, *, expected_snapshot_sha256, selection_receipt,
                         database_bytes, batch_size=50, max_records=1500):
    if type(batch_size) is not int or not 1 <= batch_size <= 100 or type(max_records) is not int or not 1 <= max_records <= 2000:
        raise ImportPaused("BOOK_CONNECTOR_EXPORT_BOUNDS")
    if not state.execute("select 1 from metadata where key='complete'").fetchone():
        raise ImportPaused("STAGING_NOT_COMPLETE")
    from .book_openlibrary_bulk import QUALITY_VERSION, SUBJECT_PROJECTION, VERSION, reviewed_hold_registry
    _, registry_sha = reviewed_hold_registry()
    if (selection_receipt.get("version") != VERSION
            or selection_receipt.get("status") != "COMPLETE"
            or selection_receipt.get("complete_dump_read") is not True
            or selection_receipt.get("source_file_verified") is not True
            or selection_receipt.get("gzip_crc_verified") is not True
            or selection_receipt.get("export_quality", {}).get("version") != QUALITY_VERSION
            or selection_receipt.get("export_quality", {}).get("reviewed_holds_sha256") != registry_sha
            or selection_receipt.get("subject_projection") != SUBJECT_PROJECTION
            or selection_receipt.get("selected_snapshot_sha256") != expected_snapshot_sha256):
        raise ImportPaused("BOOK_CONNECTOR_FULL_DUMP_RECEIPT_REQUIRED")
    if type(database_bytes) is not int or not 0 <= database_bytes < 400_000_000:
        raise ImportPaused("BOOK_CONNECTOR_CAPACITY_PREFLIGHT_REQUIRED")
    binding = json.loads(state.execute("select value from metadata where key='binding'").fetchone()[0])
    if (binding.get("input_sha256") != expected_snapshot_sha256 or binding.get("provider") != "OPEN_LIBRARY"
            or binding.get("version") != IMPORT_VERSION):
        raise ImportPaused("BOOK_CONNECTOR_STAGE_BINDING_MISMATCH")
    if state.execute("select count(*) from records").fetchone()[0] != selection_receipt.get("exported_records"):
        raise ImportPaused("BOOK_CONNECTOR_SELECTION_COUNT_MISMATCH")
    rows, planned_bytes = [], 0
    for row in state.execute("select entry from records where status='READY' order by line limit ?", (max_records,)):
        size = estimated_bytes([json.loads(row[0])])
        if database_bytes + planned_bytes + size >= 400_000_000:
            break
        rows.append(row)
        planned_bytes += size
    if not rows:
        raise ImportPaused("BOOK_CONNECTOR_NO_READY_RECORDS")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    receipts = []
    for offset in range(0, len(rows), batch_size):
        entries = [json.loads(r[0]) for r in rows[offset:offset+batch_size]]
        sql, readback, receipt = build_batch(entries, snapshot_sha256=expected_snapshot_sha256, start_line=offset+1)
        stem = f"batch-{offset//batch_size+1:03d}"
        for filename, content in ((stem+".sql", sql), (stem+"-readback.sql", readback),
                                  (stem+"-manifest.json", json.dumps(receipt, indent=2)+"\n")):
            path = directory / filename
            if path.exists() and path.read_text() != content:
                raise ImportPaused("BOOK_CONNECTOR_IMMUTABLE_EXPORT_EXISTS")
            path.write_text(content)
        receipts.append(receipt)
    return {"snapshot_sha256": expected_snapshot_sha256, "batch_size": batch_size,
            "exported_records": len(rows), "batches": receipts,
            "estimated_database_bytes": sum(r["estimated_database_bytes"] for r in receipts),
            "database_bytes_at_preflight": database_bytes,
            "projected_database_bytes": database_bytes + planned_bytes,
            "pause_threshold_bytes": 400_000_000,
            "requires_authorised_connector_application": True}
