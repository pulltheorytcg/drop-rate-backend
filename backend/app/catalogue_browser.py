"""Account-scoped catalogue browsing. Reference facts never approve physical stock."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlencode, urlsplit

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .access_control import current_access_context
from .auth import AuthenticatedUser, require_user
from .db import user_connection
from .inventory_intake import create_inventory_intake, _find_exact_catalogue, _manual_identity_key
from .physical_state import CARD_CONDITIONS
from .recognition_games import SYSTEM_BY_GAME
from .reference_market import refresh_reference_prices
from .recognition_images import reference_image_bytes
from .catalogue_artwork import reference_thumbnail
from .cardtrader_recognition import _cardtrader_image_url
from .schemas import ManualCatalogueCreate, ManualInventoryCreate

router = APIRouter(prefix="/api/v1/catalogue-browser", tags=["catalogue-browser"])
GAME_BY_SYSTEM = {system: game for game, system in SYSTEM_BY_GAME.items()}
# A browse family only: printing identities retain their original system.
BROWSE_FAMILIES = {"NARUTO": ("NARUTO_KAYOU", "NARUTO_BANDAI_LEGACY")}


def one_piece_artwork_url(value):
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
    except ValueError:
        return False
    return (url.scheme == 'https' and url.netloc in {'en.onepiece-cardgame.com','www.onepiece-cardgame.com','onepiece-cardgame.com'}
            and not url.fragment and re.fullmatch(r'/images/cardlist/card/[A-Za-z0-9_-]+\.(png|webp|jpg|jpeg)',url.path) is not None)


def with_artwork_path(row):
    item = dict(row)
    sealed=item.get('source_kind')=='SEALED_REFERENCE'
    if ((item.get('source_kind') == 'REFERENCE' and one_piece_artwork_url(item.get('image_url')))
            or (sealed and _cardtrader_image_url(item.get('image_url')))):
        item['reference_image_path'] = '/api/v1/catalogue-browser/reference-image?' + urlencode({
            field:item[field] for field in ('provider','system_code','language','provider_id')})
        if sealed:item['reference_image_path']+='&reference_kind=sealed'
    return item


def browse_systems(system_code: str) -> list[str]:
    return list(BROWSE_FAMILIES.get(system_code, (system_code,)))


def browse_games(rows) -> list[dict]:
    groups = {}
    for row in rows:
        item = dict(row)
        system = item["system_code"]
        family = next((key for key, members in BROWSE_FAMILIES.items() if system in members), system)
        if family not in groups:
            groups[family] = {"system_code": family, "game": "Naruto" if family == "NARUTO" else GAME_BY_SYSTEM.get(system, item["game"]),
                              "languages": set(), "products": 0, "sets": 0}
        group = groups[family]
        group["languages"].update(item["languages"])
        group["products"] += item["products"]
        group["sets"] += item["sets"]
    return [{**group, "languages": sorted(group["languages"])} for group in groups.values()]


GAME_CASE = "case r.system_code " + " ".join(
    "when '" + system + "' then '" + game.replace("'", "''") + "'"
    for system, game in GAME_BY_SYSTEM.items()
) + " else r.system_code end"

# Exact provider links or a previously human-selected provider printing can share
# an owned count. Card number/name alone never merges parallels or languages.
SOURCE_CTE = f"""
with reference_base as not materialized (
 select r.provider,r.system_code,r.language,r.provider_id,r.set_id,r.name,
        r.card_number,r.rarity,r.image_url,r.source_url,
        s.name as set_name,s.release_date,{GAME_CASE} as game
 from tcg.reference_cards r join tcg.reference_sets s using(provider,system_code,language,set_id)
 where (s.release_date is null or s.release_date<=current_date)
), links as (
 select r.provider,r.system_code,r.language,r.provider_id,m.catalogue_id
 from reference_base r join tcg.provider_catalogue_mappings m
 on m.source_provider=r.provider and m.system_code=r.system_code
 and m.provider_language=r.language and m.provider_id=r.provider_id
 and m.provider_entity_type='CARD_PRINTING' and m.provider_variant_key='' and m.match_status='VERIFIED'
 union
 select r.provider,r.system_code,r.language,r.provider_id,p.id
 from reference_base r join tcg.catalogue_products p
 on p.product_type='CARD' and p.game=r.game and p.name=r.name
 and p.set_name=r.set_name and p.card_number=r.card_number and p.language=r.language
 and p.variant=r.provider_id and p.rarity=coalesce(nullif(r.rarity,''),'Unknown')
), exact_links as (
 select provider,system_code,language,provider_id,(array_agg(catalogue_id))[1] as catalogue_id
 from links group by provider,system_code,language,provider_id having count(distinct catalogue_id)=1
), entries as (
 select 'r:'||md5(concat_ws(chr(31),r.provider,r.system_code,r.language,r.provider_id)) as key,
        l.catalogue_id,'CARD'::text as product_type,r.system_code,r.game,r.name,r.set_name,
        r.set_id,r.card_number,r.provider_id as variant,r.rarity,r.language,r.image_url,
        r.release_date,r.provider,r.provider_id,r.source_url,'REFERENCE'::text as source_kind,
        case when m.pricing_updated_at>=now()-interval '7 days' then m.market_value_minor end as reference_value_minor,
        case when m.pricing_updated_at>=now()-interval '7 days' then m.market_value_high_minor end as reference_value_high_minor,
        m.pricing_updated_at as reference_pricing_updated_at,
        case when m.pricing_updated_at>=now()-interval '7 days' then m.quotes else '[]'::jsonb end as market_quotes,
        (r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language in ('English','Japanese')
          and (m.expires_at is null or m.expires_at<=now() or m.refresh_revision<2)) as market_refresh_needed
 from reference_base r left join exact_links l using(provider,system_code,language,provider_id)
 left join tcg.reference_market_prices m
 on (m.provider,m.system_code,m.language,m.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and (coalesce(m.quotes->0->>'source','')<>'CARDMARKET_BULK_SINGLES'
      or m.quotes->0->'reference_identity'=jsonb_build_object(
        'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',r.set_name))
 union all
 select 's:'||md5(concat_ws(chr(31),r.provider,r.system_code,r.language,r.provider_id)),
        null::uuid,'SEALED'::text,r.system_code,{GAME_CASE},r.name,s.name,r.set_id,
        null::text,'CardTrader sealed '||r.provider_id,r.product_type,r.language,r.image_url,
        s.release_date,r.provider,r.provider_id,r.source_url,'SEALED_REFERENCE'::text,
        case when m.pricing_updated_at>=now()-interval '7 days' then m.market_value_minor end,
        case when m.pricing_updated_at>=now()-interval '7 days' then m.market_value_high_minor end,
        m.pricing_updated_at,case when m.pricing_updated_at>=now()-interval '7 days' then m.quotes else '[]'::jsonb end,false
 from tcg.reference_sealed_products r join tcg.reference_sets s using(provider,system_code,language,set_id)
 left join tcg.reference_sealed_market_prices m using(provider,system_code,language,provider_id)
 where s.release_date is null or s.release_date<=current_date
 union all
 select 'c:'||p.id::text,p.id,case when pr.collectible_type='SEALED' then 'SEALED' else p.product_type end,pr.system_code,p.game,p.name,p.set_name,
        coalesce(nullif(pr.set_code,''),p.set_name),p.card_number,p.variant,p.rarity,
        coalesce(p.language,'Unknown'),null::text,pr.release_date,''::text,''::text,null::text,'CATALOGUE'::text,
        null::bigint,null::bigint,null::timestamptz,'[]'::jsonb,false
 from tcg.catalogue_products p left join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
 where (p.product_type in ('CARD','SEALED') or (p.product_type='COLLECTION' and pr.collectible_type='SEALED')) and (pr.release_date is null or pr.release_date<=current_date)
   and not exists(select 1 from exact_links l where l.catalogue_id=p.id)
), owned as (
 select i.catalogue_id,count(*)::int as quantity,sum(i.market_value_minor) as owned_value_minor,
        count(*) filter(where i.market_value_minor is null)::int as unknown_values
 from tcg.inventory_items i where i.owner_id=$1 and i.status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
 group by i.catalogue_id
)
"""

# Sets are catalogue records in their own right. Starting from card entries hid
# known sets whose provider checklist is empty, even with ownership set to all.
SET_CTE = SOURCE_CTE + """, entry_sets as (
 select e.system_code,e.set_id,e.set_name,e.language,e.provider,min(e.game) as game,
        max(e.release_date) as release_date,count(*)::int as indexed_count,
        count(*) filter(where o.quantity>0)::int as owned_count,
        sum(o.owned_value_minor) as owned_value_minor,
        coalesce(sum(o.unknown_values),0)::int as unknown_values
 from entries e left join owned o on o.catalogue_id=e.catalogue_id
 group by e.system_code,e.set_id,e.set_name,e.language,e.provider
), set_catalogue as (
 select s.system_code,s.set_id,s.name as set_name,s.language,s.provider,
        coalesce(e.game,s.system_code) as game,s.release_date,
        coalesce(e.indexed_count,0) as indexed_count,
        greatest(coalesce(s.declared_card_count,0),coalesce(e.indexed_count,0)) as card_count,
        coalesce(e.owned_count,0) as owned_count,e.owned_value_minor,
        coalesce(e.unknown_values,0) as unknown_values
 from tcg.reference_sets s left join entry_sets e
   using(system_code,set_id,language,provider)
 where s.release_date is null or s.release_date<=current_date
 union all
 select e.system_code,e.set_id,e.set_name,e.language,e.provider,e.game,e.release_date,
        e.indexed_count,e.indexed_count,e.owned_count,e.owned_value_minor,e.unknown_values
 from entry_sets e where e.provider=''
)
"""

GAMES_SQL = SET_CTE + """
 select system_code,min(game) as game,array_agg(distinct language order by language) as languages,
        sum(indexed_count)::int as products,count(*)::int as sets
 from set_catalogue where system_code is not null group by system_code order by min(game),system_code
"""

SETS_SQL = SET_CTE + """
 , set_page as (
 select *,count(*) over()::int as total_count,
        case when indexed_count=0 then 'UNAVAILABLE'
             when card_count>indexed_count then 'PARTIAL' else 'AVAILABLE' end as checklist_status
 from set_catalogue
 where system_code=any($2::text[]) and ($3='' or language=$3)
   and ($4='' or strpos(lower(set_name),lower($4))>0 or strpos(lower(set_id),lower($4))>0)
 order by release_date desc nulls last,set_name,language,provider,set_id
 limit $5 offset $6
 )
 select page.*,preview.image_url,preview.provider_id,preview.source_kind
 from set_page page left join lateral (
   select r.image_url,r.provider_id,'REFERENCE'::text as source_kind from tcg.reference_cards r
   where r.provider=page.provider and r.system_code=page.system_code
     and r.language=page.language and r.set_id=page.set_id and r.image_url is not null
   union all
   select r.image_url,r.provider_id,'SEALED_REFERENCE'::text from tcg.reference_sealed_products r
   where r.provider=page.provider and r.system_code=page.system_code
     and r.language=page.language and r.set_id=page.set_id and r.image_url is not null
   order by provider_id limit 1
 ) preview on true
 order by page.release_date desc nulls last,page.set_name,page.language,page.provider,page.set_id
"""

# Only approved canonical media appears in catalogue results. Reference artwork
# remains clearly labelled and is never promoted into storefront media here.
MEDIA_SQL = """
 select coalesce(m.shopify_cdn_url,m.public_source_url) as url
 from tcg.media_assets m where m.catalogue_id=page.catalogue_id
 and m.scope in ('CANONICAL_CARD','CANONICAL_PRODUCT') and m.side='FRONT' and m.media_kind='IMAGE'
 and m.approval_status='APPROVED' and m.rights_status='VERIFIED'
 and m.rights_tier='STOREFRONT_ALLOWED' and m.source_status='ACTIVE' and m.revoked_at is null
 order by m.approved_at desc nulls last,m.created_at desc,m.id limit 1
"""
SORTS = {
    "name": "lower(e.name),e.key", "newest": "e.release_date desc nulls last,lower(e.name),e.key",
    "number": "e.card_number nulls last,lower(e.name),e.key",
    "value_desc": "coalesce(v.market_value_minor,e.reference_value_minor) desc nulls last,lower(e.name),e.key",
    "value_asc": "coalesce(v.market_value_minor,e.reference_value_minor) asc nulls last,lower(e.name),e.key",
}


def price_columns(entry: str) -> str:
    return f"""coalesce(v.market_value_minor,{entry}.reference_value_minor) as market_value_minor,
        case when v.market_value_minor is null then {entry}.reference_value_high_minor end as market_value_high_minor,
        coalesce(v.basis_condition,case when {entry}.reference_value_minor is not null
          then case when {entry}.source_kind='SEALED_REFERENCE' then 'Sealed · Cardmarket mixed-language guide'
            when {entry}.market_quotes->0->>'source'='CARDMARKET_BULK_SINGLES' then 'Raw · Cardmarket mixed-language guide'
            else 'Raw · Cardmarket' end end) as basis_condition,
        coalesce(v.pricing_updated_at,{entry}.reference_pricing_updated_at) as pricing_updated_at,
        case when v.market_value_minor is not null then v.valuation_source
             when {entry}.reference_value_minor is not null then case when {entry}.source_kind='SEALED_REFERENCE' then 'CARDMARKET_BULK'
               when {entry}.market_quotes->0->>'source'='CARDMARKET_BULK_SINGLES' then 'CARDMARKET_BULK_SINGLES'
               else 'TCGDEX_CARDMARKET' end
             when {entry}.market_quotes<>'[]'::jsonb then 'TCGDEX_TCGPLAYER' end as market_value_source"""


async def browser_access(request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)]) -> dict:
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        return await current_access_context(connection)


@router.get("/games")
async def games(request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)],
                access: Annotated[dict, Depends(browser_access)]):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        rows = await connection.fetch(GAMES_SQL, access["owner_id"])
    return jsonable_encoder({"items": browse_games(rows)})


@router.get("/sets")
async def sets(request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)],
               access: Annotated[dict, Depends(browser_access)], system_code: str = Query(max_length=80),
               language: str = Query(default="", max_length=80), q: str = Query(default="", max_length=160),
               limit: int = Query(default=40, ge=1, le=80), offset: int = Query(default=0, ge=0, le=100000)):
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        rows = await connection.fetch(SETS_SQL, access["owner_id"], browse_systems(system_code), language, q.strip(), limit + 1, offset)
    return jsonable_encoder({"items": [with_artwork_path(row) for row in rows[:limit]], "has_more": len(rows) > limit,
                             "offset": offset, "total_count": rows[0]["total_count"] if rows else 0,
                             "coverage": "MASTER_SET_CATALOGUE"})


def product_query(*, owner_id, q="", system_code="", language="", set_id="", provider=None,
                  product_type="", owned="all", sort="newest", keys=None, limit=40, offset=0):
    params = [owner_id]
    where = []
    def bind(value):
        params.append(value)
        return f"${len(params)}"
    if system_code:
        where.append(f"e.system_code=any({bind(browse_systems(system_code))}::text[])")
    for column, value in (("language", language), ("set_id", set_id), ("product_type", product_type)):
        if value:
            where.append(f"e.{column}={bind(value)}")
    if provider is not None:
        where.append(f"e.provider={bind(provider)}")
    if keys is not None:
        where.append(f"e.key=any({bind(keys)}::text[])")
    if owned == "owned":
        where.append("coalesce(o.quantity,0)>0")
    elif owned == "not_owned":
        where.append("coalesce(o.quantity,0)=0")
    order = SORTS[sort]
    if q.strip():
        # Every term is literal; apostrophes, % and _ never become SQL or wildcards.
        terms = bind(q.strip().split())
        number_key = re.sub(r"[^a-z0-9]", "", q.strip().lower())
        number_match = "false"
        if number_key and any(character.isdigit() for character in number_key):
            key = bind(number_key)
            number_match = f"lower(regexp_replace(coalesce(e.card_number,''),'[^A-Za-z0-9]','','g'))={key}"
        # A complete Bandai collector number is an identity lookup. Splitting
        # 'EB04 007' into broad terms also matched set OP14-EB04/card 007.
        collector_query = re.fullmatch(r'(?:OP|ST|EB|PRB|FB|FS|BT|EX|P)[\s-]*\d{0,2}[\s-]+\d{3}|(?:OP|ST|EB|PRB|FB|FS|BT|EX)\d{5}', q.strip(), re.I)
        text_match = f"""not exists (
            select 1 from unnest({terms}::text[]) term where strpos(lower(concat_ws(' ',
            e.name,e.set_name,e.card_number,e.game,e.variant,e.language,e.rarity)),lower(term))=0)"""
        where.append(number_match if collector_query else f"({number_match} or {text_match})")
        if sort in ("newest", "name", "number"):
            exact_query = bind(q.strip().lower())
            order = f"case when {number_match} then 0 when lower(e.name)={exact_query} then 1 else 2 end," + order
    clause = " and ".join(where) or "true"
    page_limit, page_offset = bind(limit + 1), bind(offset)
    # Value sorts must price the matching population before pagination. All
    # other sorts can select a page first and price only those canonical rows.
    if sort in ("value_desc", "value_asc"):
        query = SOURCE_CTE + f""", reference_values as materialized (
      select p.id,v.* from tcg.catalogue_products p
      left join lateral tcg.catalogue_reference_value_v2(p.id,nullif(p.language,'')) v on true
    ), page as (
      select e.*,coalesce(o.quantity,0) as owned_quantity,{price_columns('e')},
             row_number() over(order by {order}) as ordinal
      from entries e left join owned o on o.catalogue_id=e.catalogue_id
      left join reference_values v on v.id=e.catalogue_id
      where {clause} order by {order} limit {page_limit} offset {page_offset}
    ) select page.*,coalesce(nullif(btrim(page.image_url),''),media.url) as display_image_url,
             media.url as fallback_image_url
      from page left join lateral ({MEDIA_SQL}) media on page.catalogue_id is not null order by page.ordinal
        """
    else:
        query = SOURCE_CTE + f""", selected_page as materialized (
          select e.*,coalesce(o.quantity,0) as owned_quantity
          from entries e left join owned o on o.catalogue_id=e.catalogue_id
          where {clause} order by {order} limit {page_limit} offset {page_offset}
        ), page as (
          select e.*,row_number() over(order by {order})+{page_offset} as ordinal from selected_page e
        ) select page.*,{price_columns('page')},
                 coalesce(nullif(btrim(page.image_url),''),media.url) as display_image_url,
                 media.url as fallback_image_url
          from page left join lateral (
            select value.* from tcg.catalogue_products p
            cross join lateral tcg.catalogue_reference_value_v2(p.id,nullif(p.language,'')) value
            where p.id=page.catalogue_id
          ) v on page.catalogue_id is not null
          left join lateral ({MEDIA_SQL}) media on page.catalogue_id is not null order by page.ordinal
        """
    return query, params


@router.get("/products")
async def products(request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)],
                   access: Annotated[dict, Depends(browser_access)], q: str = Query(default="", max_length=160),
                   system_code: str = Query(default="", max_length=80), language: str = Query(default="", max_length=80),
                   set_id: str = Query(default="", max_length=200), provider: str | None = Query(default=None, max_length=80),
                   product_type: Literal["", "CARD", "SEALED"] = "", owned: Literal["all", "owned", "not_owned"] = "all",
                   sort: Literal["name", "newest", "number", "value_desc", "value_asc"] = "newest",
                   keys: str | None = Query(default=None, max_length=5000),
                   limit: int = Query(default=40, ge=1, le=80), offset: int = Query(default=0, ge=0, le=100000)):
    key_list = keys.split(",") if keys else ([] if keys is not None else None)
    if key_list is not None and len(key_list) > 100:
        raise HTTPException(422, "Watchlist is limited to 100 products")
    query, params = product_query(owner_id=access["owner_id"], q=q, system_code=system_code, language=language,
        set_id=set_id, provider=provider, product_type=product_type, owned=owned, sort=sort, keys=key_list, limit=limit, offset=offset)
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        rows = await connection.fetch(query, *params)
    return jsonable_encoder({"items": [with_artwork_path(row) for row in rows[:limit]], "has_more": len(rows) > limit, "offset": offset})


@router.get('/reference-image')
async def reference_image(request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)],
                          access: Annotated[dict, Depends(browser_access)],
                          provider: str = Query(max_length=80), system_code: str = Query(max_length=80),
                          language: str = Query(max_length=80), provider_id: str = Query(max_length=200),
                          reference_kind: Literal['card','sealed'] = 'card',
                          size: Literal['grid','detail'] = 'detail'):
    # Resolve the existing exact reference on the server. Never accept a URL
    # from the client or turn reference artwork into approved inventory media.
    async with user_connection(request.app.state.db_pool,user.user_id,request.state.request_id) as connection:
        table='reference_sealed_products' if reference_kind=='sealed' else 'reference_cards'
        url = await connection.fetchval(f'''select r.image_url from tcg.{table} r
          join tcg.reference_sets s using(provider,system_code,language,set_id)
          where r.provider=$1 and r.system_code=$2 and r.language=$3 and r.provider_id=$4
          and (s.release_date is null or s.release_date<=current_date)''',provider,system_code,language,provider_id)
    if not (_cardtrader_image_url(url) if reference_kind=='sealed' else one_piece_artwork_url(url)):
        raise HTTPException(404,'Reference artwork not available')
    payload = await (reference_thumbnail(url) if size == 'grid' else reference_image_bytes(url))
    if payload is None:
        raise HTTPException(502,'Reference artwork could not load')
    return Response(payload.data,media_type=payload.content_type,headers={'Content-Disposition':'inline'})


class ReferencePriceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[Annotated[str, Field(pattern=r"^r:[a-f0-9]{32}$")]] = Field(min_length=1, max_length=40)


@router.post("/market-values")
async def market_values(payload: ReferencePriceRequest, request: Request,
                        user: Annotated[AuthenticatedUser, Depends(require_user)],
                        access: Annotated[dict, Depends(browser_access)]):
    items = await refresh_reference_prices(request.app.state.db_pool, user.user_id, request.state.request_id,
                                           list(dict.fromkeys(payload.keys)))
    return jsonable_encoder({"items": items})


class BrowseIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=3, max_length=80)
    condition: str | None = Field(default=None, max_length=80)
    seal_status: Literal["SEALED"] | None = None
    language: Literal['English','Japanese','Chinese','Korean','French','German','Italian','Spanish'] | None = None
    confirmed: Literal[True]

    @model_validator(mode="after")
    def physical(self):
        if self.condition not in CARD_CONDITIONS and self.seal_status != "SEALED":
            raise ValueError("Choose the card condition or confirm the sealed state")
        if self.condition and self.seal_status:
            raise ValueError("A sealed product cannot have a raw card condition")
        return self


def browse_note(payload: BrowseIntake) -> str:
    # Existing in-flight card additions did not contain the new optional field.
    body=payload.model_dump_json(exclude={'language'} if payload.language is None else None)
    digest = hashlib.sha256(body.encode()).hexdigest()
    return "Human-confirmed browse " + digest + " · " + payload.key + ". Physical printing requires Drop Rate review."


def intake_payload(item: dict, payload: BrowseIntake) -> ManualInventoryCreate:
    if payload.language and item['product_type']!='SEALED':
        raise HTTPException(422,'Card language comes from its exact reference')
    if item['product_type']=='SEALED' and item.get('language')=='Unknown':
        if not payload.language:raise HTTPException(422,'Choose the physical product language')
        item={**item,'language':payload.language}
    elif payload.language and item.get('language')!=payload.language:
        raise HTTPException(422,'Product language does not match this reference')
    if item["product_type"] == "CARD" and payload.condition not in CARD_CONDITIONS:
        raise HTTPException(422, "Choose a raw card condition")
    if item["product_type"] == "SEALED" and payload.seal_status != "SEALED":
        raise HTTPException(422, "Confirm that the product is sealed")
    fields = {"condition": payload.condition, "seal_status": payload.seal_status, "identity_confirmed": False,
              "notes": browse_note(payload)}
    if item.get("catalogue_id"):
        return ManualInventoryCreate(catalogue_id=item["catalogue_id"], **fields)
    return ManualInventoryCreate(new_catalogue=reference_product(item), **fields)


def reference_product(item: dict) -> ManualCatalogueCreate:
    # Only facts re-read from a released provider record can create an identity.
    try:
        return ManualCatalogueCreate(product_type=item['product_type'], game=item["game"],
            name=item["name"], set_name=item["set_name"], card_number=item["card_number"], variant=item["provider_id"],
            rarity=item.get("rarity") or "Unknown", language=item["language"])
    except ValidationError as exc:
        raise HTTPException(422, "This reference printing needs catalogue review before it can be added") from exc


class CatalogueSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=3, max_length=80)
    confirmed: Literal[True]


@router.post("/select")
async def select_product(payload: CatalogueSelection, request: Request,
                         user: Annotated[AuthenticatedUser, Depends(require_user)],
                         access: Annotated[dict, Depends(browser_access)]):
    """Link a human-selected printing for slab intake; never create inventory."""
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        row = await connection.fetchrow(SOURCE_CTE + "select * from entries where key=$2", access["owner_id"], payload.key)
        if row is None:
            raise HTTPException(404, "Product is not available in the released catalogue")
        item = dict(row)
        if item["product_type"] != "CARD":
            raise HTTPException(422, "Graded selection supports cards only")
        if item.get("catalogue_id"):
            return {"catalogue_id": str(item["catalogue_id"])}
        if item["system_code"] not in GAME_BY_SYSTEM:
            raise HTTPException(422, "This card system needs catalogue review")
        product = reference_product(item)
        catalogue = await _find_exact_catalogue(connection, product)
        if catalogue is None:
            catalogue = await connection.fetchrow("""
                insert into tcg.catalogue_products(identity_key,product_type,game,name,set_name,card_number,variant,rarity,language)
                values($1,$2,$3,$4,$5,$6,$7,$8,$9) on conflict(identity_key) do nothing returning *
                """, _manual_identity_key(product), product.product_type, product.game, product.name,
                product.set_name, product.card_number, product.variant, product.rarity, product.language)
            if catalogue is None:
                catalogue = await _find_exact_catalogue(connection, product)
        if catalogue is None:
            raise HTTPException(409, "This printing was changed concurrently. Search again.")
        # Match existing manual browse intake: profile/identity approval remains
        # founder-only. Do not create or alter a profile through seller access.
        return {"catalogue_id": str(catalogue["id"])}


@router.post("/intake", status_code=201)
async def intake(payload: BrowseIntake, request: Request, user: Annotated[AuthenticatedUser, Depends(require_user)],
                 access: Annotated[dict, Depends(browser_access)],
                 idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=96)]):
    # Replays retain exactly the same payload even if reference data changes later.
    from .inventory_intake import _existing_receipt
    import json
    try:
        request_key = UUID(idempotency_key)
    except ValueError as exc:
        raise HTTPException(422, "Idempotency-Key must be a UUID") from exc
    async with user_connection(request.app.state.db_pool, user.user_id, request.state.request_id) as connection:
        receipt = await _existing_receipt(connection, access["owner_id"], request_key)
        if receipt:
            response = receipt["response"]
            if isinstance(response, str): response = json.loads(response)
            if response.get("inventory", {}).get("notes") != browse_note(payload):
                raise HTTPException(409, "Idempotency-Key was already used with different details")
            return {**response, "replayed": True}
        row = await connection.fetchrow(SOURCE_CTE + "select * from entries where key=$2", access["owner_id"], payload.key)
        if row is None:
            raise HTTPException(404, "Product is not available in the released catalogue")
    return await create_inventory_intake(intake_payload(dict(row), payload), request, user, idempotency_key)
