begin;

-- Canonical Japanese OP-17 booster-pack identity used by sealed recognition.
-- Bandai's official event goods page identifies the product as
-- ブースターパック 世界最強の戦士【OP-17】 and states 6 cards per pack,
-- 24 packs per box. The listed JPY price is a BOX price and is deliberately
-- not imported as a single-pack market value.
insert into tcg.catalogue_products(
    identity_key,product_type,game,name,set_name,card_number,variant,rarity,language
)
values(
    'sealed:v1:one_piece_card_game:op17:booster_pack:jp',
    'SEALED',
    'One Piece',
    'Booster Pack 世界最強の戦士 [OP-17]',
    '世界最強の戦士 [OP-17]',
    null,
    '',
    '',
    'Japanese'
)
on conflict (identity_key) do nothing;

insert into tcg.catalogue_product_profiles(
    catalogue_id,system_code,collectible_type,identity_status,set_code,
    printing_code,release_region,release_date,attributes
)
select
    p.id,
    'ONE_PIECE_CARD_GAME',
    'SEALED',
    'VERIFIED',
    'OP-17',
    null,
    'JP',
    null,
    jsonb_build_object(
        'manufacturer','Bandai',
        'language','Japanese',
        'official_name_ja','ブースターパック 世界最強の戦士【OP-17】',
        'verification_basis','Exact Bandai official product evidence',
        'official_source_url','https://cp.onepiece-cardgame.com/flame-flame-fruit/goods'
    )
from tcg.catalogue_products p
where p.identity_key='sealed:v1:one_piece_card_game:op17:booster_pack:jp'
on conflict (catalogue_id) do update
set system_code=excluded.system_code,
    collectible_type=excluded.collectible_type,
    identity_status=excluded.identity_status,
    set_code=excluded.set_code,
    release_region=excluded.release_region,
    attributes=excluded.attributes,
    updated_at=clock_timestamp(),
    version=tcg.catalogue_product_profiles.version+1;

insert into tcg.sealed_product_details(
    catalogue_id,system_code,manufacturer_sku,barcode_gtin,identity_status,
    contents,attributes
)
select
    p.id,
    'ONE_PIECE_CARD_GAME',
    'OP-17',
    null,
    'VERIFIED',
    jsonb_build_object(
        'cards_per_pack',6,
        'packs_per_box',24,
        'official_card_pool','131+4 types'
    ),
    jsonb_build_object(
        'manufacturer','Bandai',
        'region','JP',
        'language','Japanese',
        'set_code','OP-17',
        'official_name_ja','ブースターパック 世界最強の戦士【OP-17】',
        'official_source_url','https://cp.onepiece-cardgame.com/flame-flame-fruit/goods',
        'price_scope_note','Official 5,760 JPY figure is a BOX price, not a single-pack valuation'
    )
from tcg.catalogue_products p
where p.identity_key='sealed:v1:one_piece_card_game:op17:booster_pack:jp'
on conflict (catalogue_id) do update
set system_code=excluded.system_code,
    manufacturer_sku=excluded.manufacturer_sku,
    identity_status=excluded.identity_status,
    contents=excluded.contents,
    attributes=excluded.attributes,
    updated_at=clock_timestamp(),
    version=tcg.sealed_product_details.version+1;

insert into tcg.catalogue_taxonomy_assignments(
    catalogue_id,system_code,scope_kind,dimension_code,value_code,is_primary,
    verification_status,source_kind,source_reference,verified_at,metadata
)
select
    p.id,
    'ONE_PIECE_CARD_GAME',
    'SEALED',
    'SEALED_TYPE',
    'BOOSTER_PACK',
    true,
    'VERIFIED',
    'SYSTEM_RULE',
    'https://cp.onepiece-cardgame.com/flame-flame-fruit/goods',
    clock_timestamp(),
    jsonb_build_object(
        'verification_basis','Bandai official product name and pack contents'
    )
from tcg.catalogue_products p
where p.identity_key='sealed:v1:one_piece_card_game:op17:booster_pack:jp'
on conflict (catalogue_id,dimension_code,value_code) do update
set is_primary=true,
    verification_status='VERIFIED',
    source_kind='SYSTEM_RULE',
    source_reference=excluded.source_reference,
    verified_at=excluded.verified_at,
    metadata=excluded.metadata,
    updated_at=clock_timestamp();

commit;
