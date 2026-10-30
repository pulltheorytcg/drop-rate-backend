"""Bounded global-newest browsing from Railway's verified R2 catalogue.

Static ordering/identity selection runs once per published R2 generation/UTC
day in Railway. Only the requested page (at most 81 rows + bounded offset)
is passed back to PostgreSQL for its *current*, account-scoped price, owner,
media, canonical appraisal and history overlays.

Only explicitly supported text/owner/product-type shapes use a bounded
Railway shortlist; complicated searches, value sorts, watchlists, condition
pricing and ambiguous query shapes retain the original SQL fallback.
No shared R2 object contains owner or price data.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json

from .recognition_games import SYSTEM_BY_GAME

_GAME={system:game for game,system in SYSTEM_BY_GAME.items()}
_BOOKS=frozenset(("MARVEL_COMICS","DC_COMICS","OTHER_COMICS","MANGA"))
_STATIC_COLUMNS=(
    ("key","text"),("catalogue_id","uuid"),("product_type","text"),
    ("system_code","text"),("game","text"),("name","text"),("set_name","text"),
    ("set_id","text"),("card_number","text"),("variant","text"),("rarity","text"),
    ("language","text"),("image_url","text"),("release_date","date"),
    ("provider","text"),("provider_id","text"),("source_url","text"),
    ("source_kind","text"),
)


def _day(value):
    return value if isinstance(value,date) else date.fromisoformat(value) if value else None


def _released(value,today):
    dt=_day(value)
    return dt is None or dt<=today


def _key(prefix, parts):
    digest=hashlib.md5("\x1f".join(str(v) for v in parts).encode("utf-8")).hexdigest()
    return prefix+digest


def _sort_key(row):
    dt=_day(row["release_date"])
    name=row["name"]
    return (dt is None,-dt.toordinal() if dt else 0,
            name is None,name.lower() if name else "",row["key"])


@dataclass(frozen=True,slots=True)
class BrowseIndex:
    built_for: date
    entries: tuple[dict,...]

    def page(self, page_size, offset):
        if (type(page_size) is not int or not 1<=page_size<=81
                or type(offset) is not int or not 0<=offset<=512):
            raise ValueError("Global R2 browsing scope requires SQL fallback")
        return self.entries[:offset+page_size]


def build_browse_index(shared, *, today=None, verified_mappings=None):
    """Reproduce static SOURCE_CTE entries; never merge different printings."""
    today=today or datetime.now(timezone.utc).date()
    sets={
        (s["provider"],s["system_code"],s["language"],s["set_id"]):s
        for s in shared["reference_sets"] if _released(s["release_date"],today)
    }
    profiles={p["catalogue_id"]:p for p in shared["catalogue_product_profiles"]}
    canonical={p["id"]:p for p in shared["catalogue_products"]}
    canonical_identity=defaultdict(set)
    for p in shared["catalogue_products"]:
        if p["product_type"]=="CARD":
            canonical_identity[(
                p["game"],p["name"],p["set_name"],p["card_number"],
                p["language"],p["variant"],p["rarity"])].add(p["id"])
    refs=[]
    linksets=defaultdict(set)
    for r in shared["reference_cards"]:
        k=(r["provider"],r["system_code"],r["language"],r["set_id"])
        s=sets.get(k)
        if s is None:
            continue
        refs.append((r,s))
        refkey=(r["provider"],r["system_code"],r["language"],r["provider_id"])
        linksets[refkey].update(canonical_identity.get((
            _GAME.get(r["system_code"],r["system_code"]),
            r["name"],s["name"],r["card_number"],r["language"],r["provider_id"],
            r["rarity"] or "Unknown"),()))
    available={
        (r["provider"],r["system_code"],r["language"],r["provider_id"])
        for r,_ in refs
    }
    for m in verified_mappings or ():
        k=(m["source_provider"],m["system_code"],
           m["provider_language"],m["provider_id"])
        if (k in available and m["match_status"]=="VERIFIED"
                and m["provider_entity_type"]=="CARD_PRINTING"
                and m["provider_variant_key"]==""
                and m["catalogue_id"] in canonical):
            linksets[k].add(m["catalogue_id"])
    exact={key:next(iter(ids)) for key,ids in linksets.items() if len(ids)==1}
    linked=set(exact.values())
    rows=[]
    for r,s in refs:
        refkey=(r["provider"],r["system_code"],r["language"],r["provider_id"])
        rows.append(dict(
            key=_key("r:",refkey),catalogue_id=exact.get(refkey),
            product_type="CARD",system_code=r["system_code"],
            game=_GAME.get(r["system_code"],r["system_code"]),
            name=r["name"],set_name=s["name"],set_id=r["set_id"],
            card_number=r["card_number"],variant=r["provider_id"],
            rarity=r["rarity"],language=r["language"],image_url=r["image_url"],
            release_date=s["release_date"],provider=r["provider"],
            provider_id=r["provider_id"],source_url=r["source_url"],
            source_kind="REFERENCE"))
    for r in shared["reference_sealed_products"]:
        s=sets.get((r["provider"],r["system_code"],r["language"],r["set_id"]))
        if s is None:
            continue
        rows.append(dict(
            key=_key("s:",(r["provider"],r["system_code"],r["language"],r["provider_id"])),
            catalogue_id=None,product_type="SEALED",system_code=r["system_code"],
            game=_GAME.get(r["system_code"],r["system_code"]),
            name=r["name"],set_name=s["name"],set_id=r["set_id"],
            card_number=None,variant=r["provider"]+" sealed "+r["provider_id"],
            rarity=r["product_type"],language=r["language"],image_url=r["image_url"],
            release_date=s["release_date"],provider=r["provider"],
            provider_id=r["provider_id"],source_url=r["source_url"],
            source_kind="SEALED_REFERENCE"))
    for p in shared["catalogue_products"]:
        pr=profiles.get(p["id"])
        kind=pr["collectible_type"] if pr else None
        if not (p["product_type"] in ("CARD","SEALED")
                or (p["product_type"]=="COLLECTION" and kind=="SEALED")
                or (p["product_type"]=="COMIC" and kind=="COMIC" and pr
                    and pr["system_code"] in _BOOKS)):
            continue
        if not _released(pr["release_date"] if pr else None,today) or p["id"] in linked:
            continue
        rows.append(dict(
            key="c:"+p["id"],catalogue_id=p["id"],
            product_type="SEALED" if kind=="SEALED" else p["product_type"],
            system_code=pr["system_code"] if pr else None,game=p["game"],
            name=p["name"],set_name=p["set_name"],
            set_id=(pr["set_code"] if pr and pr["set_code"] else None) or p["set_name"],
            card_number=p["card_number"],variant=p["variant"],
            rarity=p["rarity"],language=p["language"] or "Unknown",
            image_url=None,release_date=pr["release_date"] if pr else None,
            provider="",provider_id="",source_url=None,source_kind="CATALOGUE"))
    return BrowseIndex(today,tuple(sorted(rows,key=_sort_key)))


def _compose_indexed_sql(query, params, rows, *, dynamic=False, market=None):
    from .catalogue_browser import SOURCE_CTE
    if not query.startswith(SOURCE_CTE):
        raise ValueError("Unrecognized R2 browse query")
    tail=query[len(SOURCE_CTE):]
    if not dynamic and "selected_page as materialized (" not in tail:
        raise ValueError("R2 browse requires a static-sort selected page")
    if dynamic:
        # Full value ordering must price every candidate. Bind the already
        # indexed R2 identities once, instead of rebuilding joins between five
        # unindexed source rowsets on every request.
        args=list(params)
        arrays=[]
        for name,kind in _STATIC_COLUMNS:
            args.append([None if row[name] is None else str(row[name]) for row in rows])
            arrays.append(f'${len(args)}::text[]')
        names=','.join(name for name,_ in _STATIC_COLUMNS)
        casts=','.join(f'x.{name}::{kind} as {name}' for name,kind in _STATIC_COLUMNS)
        transport=f'select {casts} from unnest({",".join(arrays)}) as x({names})'
    else:
        payload=json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False)
        fields=",".join(f"{name} {kind}" for name,kind in _STATIC_COLUMNS)
        args=[*params,payload]
        transport=f'select * from jsonb_to_recordset(${len(args)}::jsonb) as x({fields})'
    public_columns=",".join("st."+field for field,_ in _STATIC_COLUMNS)
    prefix=f"""
with static_page as (
  {transport}
), entries as (
 select {public_columns},
 case when st.source_kind='REFERENCE' then
   coalesce(case when m.pricing_updated_at>=now()-interval '7 days'
       then m.market_value_minor end,b.market_value_minor)
 when st.source_kind='SEALED_REFERENCE' then
   case when sm.pricing_updated_at>=now()-interval '7 days'
       then sm.market_value_minor end
 end as reference_value_minor,
 case when st.source_kind='REFERENCE' then
   case when m.pricing_updated_at>=now()-interval '7 days'
                and m.market_value_minor is not null
       then m.market_value_high_minor else b.market_value_high_minor end
 when st.source_kind='SEALED_REFERENCE' then
   case when sm.pricing_updated_at>=now()-interval '7 days'
       then sm.market_value_high_minor end
 end as reference_value_high_minor,
 case when st.source_kind='REFERENCE' then
   case when m.pricing_updated_at>=now()-interval '7 days'
                and m.market_value_minor is not null
        then m.pricing_updated_at else coalesce(b.pricing_updated_at,m.pricing_updated_at) end
 when st.source_kind='SEALED_REFERENCE' then sm.pricing_updated_at
 end as reference_pricing_updated_at,
 case when st.source_kind='REFERENCE' then
   case when m.pricing_updated_at>=now()-interval '7 days'
             and m.market_value_minor is not null then m.quotes
   else coalesce(b.quotes,'[]'::jsonb) ||
     case when m.pricing_updated_at>=now()-interval '7 days'
          then m.quotes else '[]'::jsonb end end
 when st.source_kind='SEALED_REFERENCE' then
   case when sm.pricing_updated_at>=now()-interval '7 days'
        then sm.quotes else '[]'::jsonb end
 else '[]'::jsonb end as market_quotes,
 (st.source_kind='REFERENCE' and st.provider='TCGdex'
  and st.system_code='POKEMON_TCG'
  and st.language in ('English','Japanese')
  and b.market_value_minor is null
  and (m.expires_at is null or m.expires_at<=now() or m.refresh_revision<3))
 as market_refresh_needed
 from static_page st
 left join tcg.reference_market_prices m
   on st.source_kind='REFERENCE'
  and (m.provider,m.system_code,m.language,m.provider_id)=
      (st.provider,st.system_code,st.language,st.provider_id)
  and (coalesce(m.quotes->0->>'match_basis','')<>
       'CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID'
       or st.rarity is not distinct from m.quotes->0->>'reference_rarity')
  and (coalesce(m.quotes->0->>'source','')<>'CARDMARKET_BULK_SINGLES'
       or m.quotes->0->'reference_identity'=jsonb_build_object(
        'name',st.name,'set_id',st.set_id,
        'card_number',st.card_number,'set_name',st.set_name))
 left join tcg.reference_catalogue_prices b
   on st.source_kind='REFERENCE'
  and (b.provider,b.system_code,b.language,b.provider_id)=
      (st.provider,st.system_code,st.language,st.provider_id)
  and b.pricing_updated_at>=now()-interval '7 days'
  and (b.quotes->0->>'source'<>'DROP_RATE_COMPUTED_MARKET_V1'
       or b.pricing_updated_at>now()-interval '2 days')
  and b.quotes->0->'reference_identity'=jsonb_build_object(
       'name',st.name,'set_id',st.set_id,
       'card_number',st.card_number,'set_name',st.set_name)
 left join tcg.reference_sealed_market_prices sm
   on st.source_kind='SEALED_REFERENCE'
  and (sm.provider,sm.system_code,sm.language,sm.provider_id)=
      (st.provider,st.system_code,st.language,st.provider_id)
), owned as (
 select i.catalogue_id,count(*)::int as quantity,
        sum(i.market_value_minor) as owned_value_minor,
        count(*) filter(where i.market_value_minor is null)::int as unknown_values
 from tcg.inventory_items i
 where i.owner_id=$1 and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
 group by i.catalogue_id
)
"""
    return market.sql(prefix+tail,args,rows) if market is not None else (prefix+tail,args)


def indexed_value_sql(query, params, snapshot):
    """Keep the whole candidate population and all original price/RLS rules."""
    from .catalogue_browser import SOURCE_CTE, REFERENCE_VALUES_CTE
    if (not isinstance(query,str) or not query.startswith(SOURCE_CTE)
            or REFERENCE_VALUES_CTE not in query or len(params)<3
            or len(snapshot.entries)>150000):
        raise ValueError('Unsupported R2 value ordering')
    return _compose_indexed_sql(query,params,snapshot.entries,dynamic=True)


def indexed_browse_sql(query, params, snapshot, *, max_page=81, market=None):
    """Fast default global newest case, with no query or owner filter."""
    from .catalogue_browser import SOURCE_CTE
    if not isinstance(query,str) or not query.startswith(SOURCE_CTE):
        raise ValueError("Unexpected catalogue query")
    tail=query[len(SOURCE_CTE):]
    if (len(params)!=3 or
            "selected_page as materialized (" not in tail or
            "where true order by e.release_date desc nulls last,lower(e.name),e.key" not in tail):
        raise ValueError("Default browse only")
    limit,offset=params[1],params[2]
    return _compose_indexed_sql(query,params,snapshot.page(limit,offset),market=market)


def indexed_catalogue_query(query, params, snapshot, *, owned=None, max_candidates=2000, market=None):
    """Finite R2 shortlist for text search, books, sealed and owned stock.

    The real SQL query still applies all predicates and dynamic valuation,
    image, owner and RLS rules to the shortlisted printing identities.
    """
    try:
        sql,args=indexed_browse_sql(query,params,snapshot,market=market)
        return sql,args,"NEWEST"
    except ValueError:
        pass
    from .catalogue_browser import SOURCE_CTE
    if (not isinstance(query,str) or not query.startswith(SOURCE_CTE)
            or len(params)<3):
        raise ValueError("Not a static indexed R2 page query")
    tail=query[len(SOURCE_CTE):]
    if ("selected_page as materialized (" not in tail or
            "e.release_date desc nulls last,lower(e.name),e.key" not in tail):
        raise ValueError("Dynamic value sort or unsupported query")
    limit,offset=params[-2:]
    if (type(limit) is not int or not 1<=limit<=81 or
            type(offset) is not int or not 0<=offset<=512):
        raise ValueError("Unbounded R2 page")

    mode=None
    if (len(params)==4 and isinstance(params[1],str)
            and params[1] in ("COMIC","SEALED")
            and f"where e.product_type=$2 order by" in tail):
        mode=params[1]
        rows=[row for row in snapshot.entries if row["product_type"]==mode]
        rows=rows[:offset+limit]
    elif len(params)==3 and "where coalesce(o.quantity,0)>0 order by" in tail:
        if owned is None:
            raise ValueError("Owned browser requires live RLS inventory facts")
        mode="OWNED"
        rows=[row for row in snapshot.entries
              if row["catalogue_id"] is not None
              and owned.get(row["catalogue_id"],(0,None,0))[0]>0]
        rows=rows[:offset+limit]
    elif (len(params)==5 and isinstance(params[1],list)
          and params[1] and all(isinstance(t,str) and t.isascii()
                                and not any(c.isdigit() for c in t)
                                for t in params[1])
          and isinstance(params[2],str) and params[2].isascii()
          and "where (false or not exists (" in tail):
        mode="SEARCH_TEXT"
        tokens=[term.lower() for term in params[1]]
        rows=[]
        for row in snapshot.entries:
            body=" ".join(str(row.get(k) or "") for k in (
                "name","set_name","card_number","game",
                "variant","language","rarity")).lower()
            if all(term in body for term in tokens):
                rows.append(row)
                if len(rows)>max_candidates:
                    raise ValueError("Search result exceeds bounded R2 shortlist")
    else:
        raise ValueError("Unsupported R2 browse query shape")
    return (*_compose_indexed_sql(query,params,rows,market=market),mode)
