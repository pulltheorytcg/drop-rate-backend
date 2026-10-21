"""Render a bounded, atomic, append-only SQL seed from reviewed publisher facts.

No connection, provider call, stock, price, media approval or storefront write.
Run with PYTHONPATH=backend; inspect the SQL before applying through admin tools.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.book_catalogue import publisher_page
from app.book_artwork import publisher_cover_url
from app.book_market import printing_digest
from app.book_research import source_cover_matches
from app.book_recognition import valid_book_barcode
from app.comic_identity import ComicPrintingCreate
from app.inventory_intake import _manual_identity_key
from app.schemas import ManualCatalogueCreate

MANIFEST = Path(__file__).resolve().parents[1] / "data/book_catalogue_starter_20261016.json"


def load_seed(path=MANIFEST):
    data = json.loads(path.read_text())
    entries = data["entries"]
    if not 1 <= len(entries) <= 40:
        raise ValueError("A starter batch must contain 1–40 entries")
    identities = set()
    for row in entries:
        book = ComicPrintingCreate.model_validate(row["book"])
        product = ManualCatalogueCreate(**row["catalogue"], comic_printing=book)
        if product.model_dump(exclude={"comic_printing"}) != row["catalogue"]:
            raise ValueError("Noncanonical book fields")
        if row["identity_key"] != _manual_identity_key(product) or row["identity_key"] in identities:
            raise ValueError("Duplicate or incorrect identity key")
        released = (date.fromisoformat(row["release_date"]) <= date.today() if row["release_date"]
                    else bool(book.release_year and book.release_year < date.today().year))
        if not publisher_page(row["source_url"]) or not released:
            raise ValueError("A released publisher edition is required")
        if row["identity_status"] != "STRUCTURED" or row["cover_rights_status"] != "PENDING":
            raise ValueError("A catalogue seed cannot approve a physical printing or cover rights")
        if (book.printing_number is not None or book.cover_code is not None or book.cover_artist is not None) and row.get("printing_evidence_url") != row["source_url"]:
            raise ValueError("This batch has no independently established printing or cover variant")
        if book.barcode_gtin and not valid_book_barcode(book.barcode_gtin):
            raise ValueError("Invalid book barcode")
        reference = row.get("reference")
        if reference and (reference["catalogue_id"] != row["id"] or reference["language"] != row["language"]
                or row["language"] != row["catalogue"]["language"]
                or reference["book_identity_digest"] != printing_digest(book.model_dump())
                or reference["source_url"] != row["source_url"] or reference["release_date"] != row["release_date"]
                or not publisher_cover_url(reference["image_url"])
                or not source_cover_matches(row["source_url"], reference["image_url"])
                or len(reference["observed_sha256"]) != 64
                or min(reference["observed_width"], reference["observed_height"]) < 200):
            raise ValueError("Artwork must have reviewed bytes and match the exact publisher edition")
        identities.add(row["identity_key"])
    return data


def seed_sql(data):
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if "$bookseed$" in payload or "$seedbody$" in payload:
        raise ValueError("Invalid SQL delimiter in manifest")
    return """begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $seedbody$
declare
  manifest jsonb := $bookseed$""" + payload + """$bookseed$::jsonb;
  seed_row jsonb;
  catalogue_uuid uuid;
  source_attributes jsonb;
begin
  perform pg_advisory_xact_lock(hashtext('publisher-book-catalogue-starter'));
  for seed_row in select value from jsonb_array_elements(manifest->'entries') loop
    select id into catalogue_uuid from tcg.catalogue_products where identity_key=seed_row->>'identity_key';
    if found then
      if not exists(select 1 from tcg.catalogue_products p
        join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
        join tcg.comic_printing_details b on b.catalogue_id=p.id
        where p.id=catalogue_uuid
          and (to_jsonb(p)-array['id','identity_key','created_at'])=seed_row->'catalogue'
          and pr.attributes->>'catalogue_seed_batch'=manifest->>'batch_id'
          and ((to_jsonb(b)-array['catalogue_id','identity_status','attributes','version','created_at','updated_at'])
            ||jsonb_build_object('publisher',b.attributes->>'publisher','book_format',b.attributes->>'book_format'))=seed_row->'book') then
        raise exception 'Existing catalogue identity needs review: %',seed_row->>'identity_key';
      end if;
      continue;
    end if;
    if exists(select 1 from tcg.comic_printing_details b join tcg.catalogue_products p on p.id=b.catalogue_id
      where p.language=seed_row->'catalogue'->>'language'
      and ((to_jsonb(b)-array['catalogue_id','identity_status','attributes','version','created_at','updated_at'])
        ||jsonb_build_object('publisher',b.attributes->>'publisher','book_format',b.attributes->>'book_format'))=seed_row->'book') then
      raise exception 'Equivalent book already exists under another identity';
    end if;
    catalogue_uuid := (seed_row->>'id')::uuid;
    source_attributes := jsonb_build_object(
      'publisher',seed_row->'book'->>'publisher','book_format',seed_row->'book'->>'book_format',
      'identity_source','OFFICIAL_PUBLISHER_CATALOGUE','catalogue_seed_batch',manifest->>'batch_id',
      'source_url',seed_row->>'source_url','source_checked_at',seed_row->>'source_checked_at',
      'cover_source_url',seed_row->'cover_source_url','cover_rights_status','PENDING',
      'verification_scope',seed_row->>'verification_scope',
      'publisher_reference',seed_row->'reference');
    insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
    select catalogue_uuid,seed_row->>'identity_key','COMIC',p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language
    from jsonb_to_record(seed_row->'catalogue') p(game text,name text,set_name text,card_number text,variant text,rarity text,language text);
    insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,identity_status,release_date,attributes)
    values(catalogue_uuid,seed_row->'book'->>'system_code','COMIC','STRUCTURED',(seed_row->>'release_date')::date,source_attributes);
    insert into tcg.comic_printing_details(catalogue_id,system_code,series_title,volume_identifier,issue_number,
      printing_number,release_year,cover_code,cover_artist,barcode_gtin,identity_status,attributes)
    select catalogue_uuid,b.system_code,b.series_title,b.volume_identifier,b.issue_number,
      b.printing_number,b.release_year,b.cover_code,b.cover_artist,b.barcode_gtin,'STRUCTURED',source_attributes
    from jsonb_to_record(seed_row->'book') b(system_code text,series_title text,volume_identifier text,issue_number text,
      printing_number int,release_year int,cover_code text,cover_artist text,barcode_gtin text);
  end loop;
end;
$seedbody$;
commit;
"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=MANIFEST)
    print(seed_sql(load_seed(parser.parse_args().manifest)))
