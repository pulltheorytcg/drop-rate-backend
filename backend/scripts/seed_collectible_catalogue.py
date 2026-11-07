"""Render reviewed Sports/Figures metadata as atomic SQL.

This command opens no database connection and makes no network calls. It never
creates stock, prices, media, publication records or seller verification. Inspect
the SQL, then apply it through the normal reviewed database release process.
"""
from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from app.manual_collectible_identity import FigureDetailsCreate, SportsCardCreate
from app.schemas import ManualCatalogueCreate

MANIFEST = Path(__file__).resolve().parents[1] / "data/collectible_catalogue_starter_20261103.json"
SCOPE = "OFFICIAL_REFERENCE_METADATA_ONLY"
SOURCE_HOSTS = frozenset({
    "www.topps.com", "topps.com", "uk.topps.com", "ripped.topps.com",
    "www.arsenal.com", "www.chelseafc.com", "www.liverpoolfc.com", "www.mancity.com",
    "www.goodsmile.com", "info.goodsmile.com", "tamashiiweb.com",
})
CHECKLIST_PATH = "/s/files/1/0739/2015/1805/files/Topps_Premier_League_2026_Hobby_Checklist.pdf"
ROW_KEYS = frozenset({
    "id", "identity_key", "source_id", "source_url", "source_checked_at",
    "source_evidence", "catalogue", "sports_card", "figure_details",
    "identity_status", "verification_scope", "release_date", "release_month",
    "release_region", "language_scope",
})


def official_source_url(value: str) -> bool:
    """Only reviewed public publisher/club origins, never a fetching capability."""
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.username or url.password or url.port or url.fragment:
            return False
        if url.hostname == "cdn.shopify.com":
            return url.path == CHECKLIST_PATH and url.query in {"", "v=1756731624"}
        return url.hostname in SOURCE_HOSTS and not url.query and url.path.startswith("/")
    except (TypeError, ValueError):
        return False


def official_identity_key(system_code: str, source_id: str, language: str | None) -> str:
    """Source edition IDs are stable even if a later correction needs review."""
    identity = json.dumps([system_code, source_id, language], ensure_ascii=False, separators=(",", ":"))
    return "official-collectible:v1:" + hashlib.sha256(identity.encode()).hexdigest()


def validate_seed(data: dict) -> dict:
    if set(data) != {"batch_id", "entries"} or not re.fullmatch(r"[a-z0-9_-]{1,100}", data["batch_id"]):
        raise ValueError("Invalid starter batch")
    if not isinstance(data["entries"], list) or not 1 <= len(data["entries"]) <= 20:
        raise ValueError("A starter batch must contain 1–20 entries")
    identities, source_ids = set(), set()
    for row in data["entries"]:
        if set(row) != ROW_KEYS:
            raise ValueError("Unexpected or missing metadata; this seed cannot import prices, stock or artwork")
        if bool(row["sports_card"]) == bool(row["figure_details"]):
            raise ValueError("Choose one typed collectible identity")
        field = "sports_card" if row["sports_card"] else "figure_details"
        model = SportsCardCreate if field == "sports_card" else FigureDetailsCreate
        details = model.model_validate(row[field])
        if details.model_dump() != row[field]:
            raise ValueError("Typed identity must be canonical and explicit")
        product = ManualCatalogueCreate(**row["catalogue"], **{field: details})
        canonical = product.model_dump(exclude={"sports_card", "figure_details", "comic_printing"})
        if canonical != row["catalogue"]:
            raise ValueError("Noncanonical catalogue fields")
        if not re.fullmatch(r"[a-z0-9:_-]{1,160}", row["source_id"]):
            raise ValueError("A stable official source edition ID is required")
        key = official_identity_key(details.system_code, row["source_id"], product.language)
        if row["identity_key"] != key or row["id"] != str(uuid5(NAMESPACE_URL, key)):
            raise ValueError("Incorrect official identity key or catalogue ID")
        if key in identities or row["source_id"] in source_ids:
            raise ValueError("Duplicate official source identity")
        if row["identity_status"] != "VERIFIED" or row["verification_scope"] != SCOPE:
            raise ValueError("Only official reference metadata is verified by this seed")
        checked = date.fromisoformat(row["source_checked_at"])
        if checked > date.today() or not official_source_url(row["source_url"]):
            raise ValueError("A reviewed official source and nonfuture review date are required")
        evidence = row["source_evidence"]
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
            raise ValueError("Specific official source evidence is required")
        for source in evidence:
            if set(source) != {"url", "locator", "fields"} or not official_source_url(source["url"]):
                raise ValueError("Invalid official evidence URL or fields")
            if not isinstance(source["locator"], str) or not 1 <= len(source["locator"]) <= 500:
                raise ValueError("Evidence must identify a page, row or section")
            if not isinstance(source["fields"], list) or not source["fields"] or not all(
                isinstance(item, str) and re.fullmatch(r"[a-z_]{1,80}", item) for item in source["fields"]
            ):
                raise ValueError("Evidence must identify the supported fields")
        if row["source_url"] not in {source["url"] for source in evidence}:
            raise ValueError("Primary source is missing from evidence")
        if row["release_date"]:
            released_by = date.fromisoformat(row["release_date"])
        elif row["release_month"]:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", row["release_month"]):
                raise ValueError("Invalid release month")
            year, month = map(int, row["release_month"].split("-"))
            released_by = date(year, month, monthrange(year, month)[1])
        elif details.release_year:
            released_by = date(details.release_year, 12, 31)
        else:
            raise ValueError("Released catalogue metadata is required")
        if released_by > checked or released_by.year != details.release_year:
            raise ValueError("Future or inconsistent release metadata")
        if row["release_date"] and row["release_month"] and not row["release_date"].startswith(row["release_month"]):
            raise ValueError("Release date and month disagree")
        if row["release_region"] is not None and not re.fullmatch(r"[A-Z]{2}", row["release_region"]):
            raise ValueError("Use an explicit country code or leave region unknown")
        if not isinstance(row["language_scope"], str) or not 1 <= len(row["language_scope"]) <= 500:
            raise ValueError("Explain the catalogue language scope")
        identities.add(key)
        source_ids.add(row["source_id"])
    return data


def load_seed(path=MANIFEST):
    return validate_seed(json.loads(Path(path).read_text()))


def seed_sql(data):
    """Append-only references; update category coverage only after validation."""
    validate_seed(data)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if "$collectibleseed$" in payload or "$seedbody$" in payload:
        raise ValueError("Invalid SQL delimiter in manifest")
    return """begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
-- Prevent a concurrent manual insert from racing the equivalent-identity check.
lock table tcg.catalogue_products, tcg.catalogue_product_profiles, tcg.collectible_systems in share row exclusive mode;
do $seedbody$
declare
  manifest jsonb := $collectibleseed$""" + payload + """$collectibleseed$::jsonb;
  seed_row jsonb;
  catalogue_uuid uuid;
  detail_key text;
  system text;
  source_attributes jsonb;
begin
  perform pg_advisory_xact_lock(hashtext('official-collectible-catalogue-starter'));
  for seed_row in select value from jsonb_array_elements(manifest->'entries') loop
    detail_key := case when seed_row->'sports_card'<>'null'::jsonb then 'sports_card' else 'figure_details' end;
    system := seed_row->detail_key->>'system_code';
    source_attributes := jsonb_build_object(
      detail_key,seed_row->detail_key,
      'identity_source','OFFICIAL_CATALOGUE','catalogue_seed_batch',manifest->>'batch_id',
      'official_source_id',seed_row->>'source_id','source_url',seed_row->>'source_url',
      'source_checked_at',seed_row->>'source_checked_at','source_evidence',seed_row->'source_evidence',
      'verification_scope',seed_row->>'verification_scope','release_month',seed_row->'release_month',
      'language_scope',seed_row->>'language_scope');
    select id into catalogue_uuid from tcg.catalogue_products where identity_key=seed_row->>'identity_key';
    if found then
      if not exists(select 1 from tcg.catalogue_products p
        join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
        where p.id=catalogue_uuid and p.id=(seed_row->>'id')::uuid
          and jsonb_build_object('product_type',p.product_type,'game',p.game,'name',p.name,
            'set_name',p.set_name,'card_number',p.card_number,'variant',p.variant,
            'rarity',p.rarity,'language',p.language)=seed_row->'catalogue'
          and pr.system_code=system and pr.collectible_type=seed_row->'catalogue'->>'product_type'
          and pr.identity_status='VERIFIED' and pr.attributes=source_attributes
          and pr.release_date is not distinct from (seed_row->>'release_date')::date
          and pr.release_region is not distinct from seed_row->>'release_region') then
        raise exception 'Existing official catalogue identity needs review: %',seed_row->>'source_id';
      end if;
      continue;
    end if;
    if exists(select 1 from tcg.catalogue_products p
      left join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
      where pr.attributes->>'official_source_id'=seed_row->>'source_id'
        or (p.product_type=seed_row->'catalogue'->>'product_type'
          and lower(p.game)=lower(seed_row->'catalogue'->>'game')
          and lower(p.name)=lower(seed_row->'catalogue'->>'name')
          and lower(p.set_name)=lower(seed_row->'catalogue'->>'set_name')
          and lower(coalesce(p.card_number,''))=lower(coalesce(seed_row->'catalogue'->>'card_number',''))
          and lower(coalesce(p.variant,''))=lower(coalesce(seed_row->'catalogue'->>'variant',''))
          and lower(coalesce(p.language,''))=lower(coalesce(seed_row->'catalogue'->>'language','')))) then
      raise exception 'Equivalent collectible exists under another identity; review required: %',seed_row->>'source_id';
    end if;
    catalogue_uuid := (seed_row->>'id')::uuid;
    insert into tcg.catalogue_products(id,identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
    select catalogue_uuid,seed_row->>'identity_key',p.product_type,p.game,p.name,p.set_name,p.card_number,p.variant,p.rarity,p.language
    from jsonb_to_record(seed_row->'catalogue') p(product_type text,game text,name text,set_name text,card_number text,variant text,rarity text,language text);
    insert into tcg.catalogue_product_profiles(catalogue_id,system_code,collectible_type,identity_status,release_date,release_region,attributes)
    values(catalogue_uuid,system,seed_row->'catalogue'->>'product_type','VERIFIED',
      (seed_row->>'release_date')::date,seed_row->>'release_region',source_attributes);
  end loop;
  -- Coverage follows actual, reviewed rows and is changed only after the whole
  -- reference batch succeeds. A replay leaves metadata and timestamps intact.
  with counts as (
    select pr.system_code,count(*)::int as reference_count
    from tcg.catalogue_product_profiles pr
    where pr.identity_status='VERIFIED' and pr.attributes->>'identity_source'='OFFICIAL_CATALOGUE'
      and pr.system_code in (
        select coalesce(value->'sports_card'->>'system_code',value->'figure_details'->>'system_code')
        from jsonb_array_elements(manifest->'entries'))
    group by pr.system_code
  ), coverage as (
    select s.code,s.metadata || jsonb_build_object('reference_catalogue_available',true,
      'reference_catalogue_coverage','STARTER_METADATA','official_reference_count',c.reference_count) as metadata
    from tcg.collectible_systems s join counts c on c.system_code=s.code
  )
  update tcg.collectible_systems s set metadata=c.metadata,updated_at=now()
  from coverage c where s.code=c.code and s.metadata is distinct from c.metadata;
end;
$seedbody$;
commit;
"""


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", type=Path, default=MANIFEST)
    print(seed_sql(load_seed(parser.parse_args().manifest)))
