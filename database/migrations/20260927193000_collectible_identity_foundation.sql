begin;

-- Universal collectible identity foundation.
-- Existing catalogue_products/inventory_items remain authoritative and intact.
-- This layer adds structured exact-printing identity alongside legacy rarity/variant fields.

alter table tcg.catalogue_products
    drop constraint if exists catalogue_products_product_type_check;

alter table tcg.catalogue_products
    add constraint catalogue_products_product_type_check
    check (product_type in ('CARD','SEALED','COLLECTION','COMIC','ACCESSORY'));

create table tcg.collectible_systems (
    code text primary key
        check (code ~ '^[A-Z0-9_]{2,80}$'),
    display_name text not null
        check (length(btrim(display_name)) between 1 and 160),
    franchise text not null
        check (length(btrim(franchise)) between 1 and 160),
    system_kind text not null
        check (system_kind in ('TCG','COMICS')),
    publisher text,
    lifecycle_status text not null default 'ACTIVE'
        check (lifecycle_status in ('ACTIVE','ANNOUNCED','INACTIVE')),
    official_url text
        check (official_url is null or official_url ~ '^https://'),
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table tcg.catalogue_product_profiles (
    catalogue_id uuid primary key references tcg.catalogue_products(id),
    system_code text not null references tcg.collectible_systems(code),
    collectible_type text not null
        check (collectible_type in ('CARD','SEALED','COMIC','ACCESSORY')),
    identity_status text not null default 'LEGACY_UNREVIEWED'
        check (identity_status in ('LEGACY_UNREVIEWED','STRUCTURED','VERIFIED','NEEDS_REVIEW')),
    set_code text,
    printing_code text,
    release_region text,
    release_date date,
    attributes jsonb not null default '{}'::jsonb,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index catalogue_product_profiles_system_idx
    on tcg.catalogue_product_profiles(system_code, collectible_type, identity_status);

create table tcg.taxonomy_schemas (
    system_code text not null references tcg.collectible_systems(code),
    scope_kind text not null
        check (scope_kind in ('CARD','SEALED','COMIC','ACCESSORY')),
    dimension_code text not null
        check (dimension_code ~ '^[A-Z0-9_]{2,80}$'),
    display_name text not null,
    cardinality text not null
        check (cardinality in ('SINGLE','MULTI')),
    required_for_verified boolean not null default false,
    official_source_url text
        check (official_source_url is null or official_source_url ~ '^https://'),
    metadata jsonb not null default '{}'::jsonb,
    primary key (system_code, scope_kind, dimension_code)
);

create table tcg.taxonomy_values (
    system_code text not null,
    scope_kind text not null,
    dimension_code text not null,
    value_code text not null
        check (value_code ~ '^[A-Z0-9_]{1,100}$'),
    display_name text not null,
    aliases text[] not null default '{}'::text[],
    canonical boolean not null default true,
    active boolean not null default true,
    source_reference text
        check (source_reference is null or source_reference ~ '^https://'),
    metadata jsonb not null default '{}'::jsonb,
    primary key (system_code, scope_kind, dimension_code, value_code),
    foreign key (system_code, scope_kind, dimension_code)
        references tcg.taxonomy_schemas(system_code, scope_kind, dimension_code)
);

create index taxonomy_values_lookup_idx
    on tcg.taxonomy_values(system_code, scope_kind, dimension_code, active);

create table tcg.catalogue_taxonomy_assignments (
    id uuid primary key default gen_random_uuid(),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    system_code text not null,
    scope_kind text not null,
    dimension_code text not null,
    value_code text not null,
    is_primary boolean not null default false,
    verification_status text not null default 'MIGRATED_UNVERIFIED'
        check (verification_status in ('MIGRATED_UNVERIFIED','VERIFIED')),
    source_kind text not null
        check (source_kind in ('LEGACY_IMPORT','PROVIDER_EXACT','MANUAL','SYSTEM_RULE')),
    source_reference text
        check (source_reference is null or source_reference ~ '^https://'),
    verified_by_user_id uuid references auth.users(id),
    verified_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (catalogue_id, dimension_code, value_code),
    foreign key (system_code, scope_kind, dimension_code, value_code)
        references tcg.taxonomy_values(system_code, scope_kind, dimension_code, value_code),
    check (
        (verification_status='VERIFIED' and verified_at is not null)
        or
        (verification_status='MIGRATED_UNVERIFIED'
         and verified_at is null
         and verified_by_user_id is null)
    )
);

create index catalogue_taxonomy_by_catalogue_idx
    on tcg.catalogue_taxonomy_assignments(catalogue_id, dimension_code);
create unique index catalogue_taxonomy_primary_dimension_idx
    on tcg.catalogue_taxonomy_assignments(catalogue_id, dimension_code)
    where is_primary;

create table tcg.card_gameplay_identities (
    id uuid primary key default gen_random_uuid(),
    system_code text not null references tcg.collectible_systems(code),
    native_identity_key text not null,
    canonical_name text not null,
    card_number text,
    identity_status text not null default 'LEGACY_UNREVIEWED'
        check (identity_status in ('LEGACY_UNREVIEWED','STRUCTURED','VERIFIED','NEEDS_REVIEW')),
    attributes jsonb not null default '{}'::jsonb,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (system_code, native_identity_key)
);

create index card_gameplay_identity_number_idx
    on tcg.card_gameplay_identities(system_code, card_number);

create table tcg.card_printings (
    catalogue_id uuid primary key references tcg.catalogue_products(id),
    gameplay_identity_id uuid not null references tcg.card_gameplay_identities(id),
    system_code text not null references tcg.collectible_systems(code),
    printing_key text not null,
    identity_status text not null default 'LEGACY_UNREVIEWED'
        check (identity_status in ('LEGACY_UNREVIEWED','STRUCTURED','VERIFIED','NEEDS_REVIEW')),
    attributes jsonb not null default '{}'::jsonb,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (system_code, printing_key)
);

create index card_printings_gameplay_idx
    on tcg.card_printings(gameplay_identity_id, identity_status);

create table tcg.sealed_product_details (
    catalogue_id uuid primary key references tcg.catalogue_products(id),
    system_code text not null references tcg.collectible_systems(code),
    manufacturer_sku text,
    barcode_gtin text,
    identity_status text not null default 'LEGACY_UNREVIEWED'
        check (identity_status in ('LEGACY_UNREVIEWED','STRUCTURED','VERIFIED','NEEDS_REVIEW')),
    contents jsonb not null default '{}'::jsonb,
    attributes jsonb not null default '{}'::jsonb,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index sealed_product_sku_idx
    on tcg.sealed_product_details(system_code, manufacturer_sku)
    where manufacturer_sku is not null;
create index sealed_product_barcode_idx
    on tcg.sealed_product_details(barcode_gtin)
    where barcode_gtin is not null;

create table tcg.comic_printing_details (
    catalogue_id uuid primary key references tcg.catalogue_products(id),
    system_code text not null references tcg.collectible_systems(code),
    series_title text not null,
    volume_identifier text,
    issue_number text not null,
    printing_number integer check (printing_number is null or printing_number >= 1),
    release_year integer check (release_year is null or release_year between 1930 and 2200),
    cover_code text,
    cover_artist text,
    barcode_gtin text,
    identity_status text not null default 'STRUCTURED'
        check (identity_status in ('LEGACY_UNREVIEWED','STRUCTURED','VERIFIED','NEEDS_REVIEW')),
    attributes jsonb not null default '{}'::jsonb,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index comic_printing_lookup_idx
    on tcg.comic_printing_details(system_code, series_title, issue_number);
create index comic_printing_barcode_idx
    on tcg.comic_printing_details(barcode_gtin)
    where barcode_gtin is not null;

create table tcg.provider_catalogue_mappings (
    id uuid primary key default gen_random_uuid(),
    catalogue_id uuid not null references tcg.catalogue_products(id),
    system_code text not null references tcg.collectible_systems(code),
    source_provider text not null,
    provider_entity_type text not null
        check (provider_entity_type in ('CARD_PRINTING','SEALED_PRODUCT','COMIC_PRINTING','ACCESSORY')),
    provider_id text not null,
    provider_variant_key text not null default '',
    provider_language text not null default '',
    source_reference text
        check (source_reference is null or source_reference ~ '^https://'),
    match_status text not null default 'REVIEW'
        check (match_status in ('REVIEW','VERIFIED','REJECTED','RETIRED')),
    verification_basis text not null
        check (verification_basis in ('LEGACY_IMPORT','DETERMINISTIC_EXACT','HUMAN','AI_SUGGESTED')),
    confidence numeric(5,4) not null default 0
        check (confidence between 0 and 1),
    verified_by_user_id uuid references auth.users(id),
    verified_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    version integer not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (
        source_provider,
        provider_entity_type,
        provider_id,
        provider_variant_key,
        provider_language
    ),
    check (
        match_status <> 'VERIFIED'
        or (
            verification_basis in ('DETERMINISTIC_EXACT','HUMAN')
            and verified_at is not null
        )
    ),
    check (
        verification_basis <> 'AI_SUGGESTED'
        or match_status <> 'VERIFIED'
    ),
    check (
        verification_basis <> 'HUMAN'
        or match_status <> 'VERIFIED'
        or verified_by_user_id is not null
    )
);

create index provider_catalogue_mapping_catalogue_idx
    on tcg.provider_catalogue_mappings(catalogue_id, source_provider, match_status);

-- Configuration registry. Unknown values are deliberate: a new game mechanic
-- must fail closed instead of being forced into the closest existing category.
insert into tcg.collectible_systems(
    code,display_name,franchise,system_kind,publisher,lifecycle_status,official_url,metadata
) values
    ('POKEMON_TCG','Pokémon Trading Card Game','Pokémon','TCG','The Pokémon Company','ACTIVE','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards','{}'),
    ('ONE_PIECE_CARD_GAME','One Piece Card Game','One Piece','TCG','Bandai','ACTIVE','https://en.onepiece-cardgame.com/','{}'),
    ('DRAGON_BALL_SUPER_MASTERS','Dragon Ball Super Card Game Masters','Dragon Ball','TCG','Bandai','ACTIVE','https://www.dbs-cardgame.com/us-en/','{}'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','Dragon Ball Super Card Game Fusion World','Dragon Ball','TCG','Bandai','ACTIVE','https://www.dbs-cardgame.com/fw/en/','{}'),
    ('DISNEY_LORCANA','Disney Lorcana','Disney','TCG','Ravensburger','ACTIVE','https://www.disneylorcana.com/','{}'),
    ('RIFTBOUND','Riftbound: League of Legends Trading Card Game','League of Legends','TCG','Riot Games','ACTIVE','https://playriftbound.com/','{}'),
    ('NARUTO_BANDAI','Naruto Bandai Card Game','Naruto','TCG','Bandai','ANNOUNCED',null,'{"source":"product_roadmap"}'),
    ('MARVEL_COMICS','Marvel Comics','Marvel','COMICS','Marvel','ACTIVE','https://www.marvel.com/comics','{}'),
    ('DC_COMICS','DC Comics','DC','COMICS','DC','ACTIVE','https://www.dc.com/comics','{}');

-- Every TCG gets the same high-level recognition dimensions; values remain
-- system-specific and can evolve without another schema redesign.
insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
)
select code,'CARD','CARD_TYPE','Card type',
       case when code='RIFTBOUND' then 'MULTI' else 'SINGLE' end,
       true,official_url
from tcg.collectible_systems
where system_kind='TCG';

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
)
select code,'CARD','RARITY','Rarity','SINGLE',false,official_url
from tcg.collectible_systems
where system_kind='TCG';

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
)
select code,'CARD','ART_TREATMENT','Artwork treatment','MULTI',true,official_url
from tcg.collectible_systems
where system_kind='TCG';

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
)
select code,'CARD','FINISH','Finish / surface treatment','MULTI',false,official_url
from tcg.collectible_systems
where system_kind='TCG';

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
)
select code,'CARD','SPECIAL_CLASSIFICATION','Special classification','MULTI',false,official_url
from tcg.collectible_systems
where system_kind='TCG';

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
) values
    ('ONE_PIECE_CARD_GAME','CARD','COLOR','Color','MULTI',false,'https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','ATTRIBUTE','Attribute','MULTI',false,'https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('DISNEY_LORCANA','CARD','COLOR','Ink color','MULTI',false,'https://cards.disneylorcana.com/en-US/'),
    ('RIFTBOUND','CARD','DOMAIN','Domain','MULTI',false,'https://playriftbound.com/en-us/rules-hub/');

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
)
select code,'SEALED','SEALED_TYPE','Sealed product type','SINGLE',true,official_url
from tcg.collectible_systems
where system_kind='TCG';

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
)
select code,'SEALED','EDITION','Edition / configuration','MULTI',false,official_url
from tcg.collectible_systems
where system_kind='TCG';

insert into tcg.taxonomy_schemas(
    system_code,scope_kind,dimension_code,display_name,cardinality,required_for_verified,official_source_url
) values
    ('MARVEL_COMICS','COMIC','COMIC_COVER_VARIANT','Cover variant','MULTI',true,'https://www.marvel.com/comics'),
    ('MARVEL_COMICS','COMIC','COMIC_TREATMENT','Cover / print treatment','MULTI',false,'https://www.marvel.com/comics'),
    ('MARVEL_COMICS','COMIC','COMIC_PRINTING_CLASS','Printing class','SINGLE',true,'https://www.marvel.com/comics'),
    ('DC_COMICS','COMIC','COMIC_COVER_VARIANT','Cover variant','MULTI',true,'https://www.dc.com/comics'),
    ('DC_COMICS','COMIC','COMIC_TREATMENT','Cover / print treatment','MULTI',false,'https://www.dc.com/comics'),
    ('DC_COMICS','COMIC','COMIC_PRINTING_CLASS','Printing class','SINGLE',true,'https://www.dc.com/comics');

-- Unknown is always a legal taxonomy state, but never enough by itself to
-- produce a VERIFIED exact-printing identity.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,canonical,metadata
)
select system_code,scope_kind,dimension_code,'UNKNOWN','Unknown / unresolved',true,'{"fail_closed":true}'::jsonb
from tcg.taxonomy_schemas;

-- One Piece official card categories.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases,source_reference
) values
    ('ONE_PIECE_CARD_GAME','CARD','CARD_TYPE','LEADER','Leader','{"L"}','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','CARD_TYPE','CHARACTER','Character','{}','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','CARD_TYPE','EVENT','Event','{}','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','CARD_TYPE','STAGE','Stage','{}','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','CARD_TYPE','DON','DON!!','{"DON!!"}','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases,source_reference
) values
    ('ONE_PIECE_CARD_GAME','CARD','RARITY','C','Common','{"C"}','https://en.onepiece-cardgame.com/'),
    ('ONE_PIECE_CARD_GAME','CARD','RARITY','UC','Uncommon','{"UC"}','https://en.onepiece-cardgame.com/'),
    ('ONE_PIECE_CARD_GAME','CARD','RARITY','R','Rare','{"R"}','https://en.onepiece-cardgame.com/'),
    ('ONE_PIECE_CARD_GAME','CARD','RARITY','SR','Super Rare','{"SR"}','https://en.onepiece-cardgame.com/'),
    ('ONE_PIECE_CARD_GAME','CARD','RARITY','SEC','Secret Rare','{"SEC"}','https://en.onepiece-cardgame.com/'),
    ('ONE_PIECE_CARD_GAME','CARD','RARITY','L','Leader','{"L"}','https://en.onepiece-cardgame.com/');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases,source_reference
) values
    ('ONE_PIECE_CARD_GAME','CARD','SPECIAL_CLASSIFICATION','PROMO','Promo','{"PR","Promo"}','https://en.onepiece-cardgame.com/'),
    ('ONE_PIECE_CARD_GAME','CARD','SPECIAL_CLASSIFICATION','SP','SP','{}','https://en.onepiece-cardgame.com/'),
    ('ONE_PIECE_CARD_GAME','CARD','SPECIAL_CLASSIFICATION','TREASURE_RARE','Treasure Rare','{"TR"}','https://en.onepiece-cardgame.com/');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases
) values
    ('ONE_PIECE_CARD_GAME','CARD','ART_TREATMENT','BASE','Base / standard art','{}'),
    ('ONE_PIECE_CARD_GAME','CARD','ART_TREATMENT','PARALLEL','Parallel','{}'),
    ('ONE_PIECE_CARD_GAME','CARD','ART_TREATMENT','ALTERNATE_ART','Alternate Art','{"Alt Art"}'),
    ('ONE_PIECE_CARD_GAME','CARD','ART_TREATMENT','MANGA','Manga','{}'),
    ('ONE_PIECE_CARD_GAME','CARD','ART_TREATMENT','SUPER_PARALLEL','Super Parallel','{}'),
    ('ONE_PIECE_CARD_GAME','CARD','FINISH','NORMAL','Normal / standard finish','{}'),
    ('ONE_PIECE_CARD_GAME','CARD','FINISH','FOIL','Foil','{}'),
    ('ONE_PIECE_CARD_GAME','CARD','FINISH','TEXTURED','Textured','{}');

-- One Piece rules define six colors and five attributes.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,source_reference
) values
    ('ONE_PIECE_CARD_GAME','CARD','COLOR','RED','Red','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','COLOR','GREEN','Green','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','COLOR','BLUE','Blue','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','COLOR','PURPLE','Purple','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','COLOR','BLACK','Black','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','COLOR','YELLOW','Yellow','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','ATTRIBUTE','SLASH','Slash','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','ATTRIBUTE','STRIKE','Strike','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','ATTRIBUTE','RANGED','Ranged','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','ATTRIBUTE','SPECIAL','Special','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf'),
    ('ONE_PIECE_CARD_GAME','CARD','ATTRIBUTE','WISDOM','Wisdom','https://en.onepiece-cardgame.com/pdf/rule_comprehensive.pdf');

-- Pokémon official database categories and rarity vocabulary.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases,source_reference
) values
    ('POKEMON_TCG','CARD','CARD_TYPE','POKEMON','Pokémon','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','CARD_TYPE','TRAINER_ITEM','Trainer - Item','{"Trainer-Item"}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','CARD_TYPE','TRAINER_SUPPORTER','Trainer - Supporter','{"Trainer-Supporter"}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','CARD_TYPE','TRAINER_STADIUM','Trainer - Stadium','{"Trainer-Stadium"}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','CARD_TYPE','POKEMON_TOOL','Pokémon Tool','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','CARD_TYPE','TECHNICAL_MACHINE','Technical Machine','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','CARD_TYPE','ENERGY_BASIC','Basic Energy','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','CARD_TYPE','ENERGY_SPECIAL','Special Energy','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases,source_reference
) values
    ('POKEMON_TCG','CARD','RARITY','COMMON','Common','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','UNCOMMON','Uncommon','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','RARE','Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','RARE_HOLO','Rare Holo','{"Holo Rare"}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','DOUBLE_RARE','Double Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','ULTRA_RARE','Ultra Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','ILLUSTRATION_RARE','Illustration Rare','{"Art Rare"}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','SPECIAL_ILLUSTRATION_RARE','Special Illustration Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','HYPER_RARE','Hyper Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','SHINY_RARE','Shiny Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','SHINY_ULTRA_RARE','Shiny Ultra Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','PROMO','Promo','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','MEGA_ATTACK_RARE','Mega Attack Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards'),
    ('POKEMON_TCG','CARD','RARITY','MEGA_HYPER_RARE','Mega Hyper Rare','{}','https://www.pokemon.com/us/pokemon-tcg/pokemon-cards');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases
) values
    ('POKEMON_TCG','CARD','ART_TREATMENT','BASE','Base / standard art','{}'),
    ('POKEMON_TCG','CARD','ART_TREATMENT','FULL_ART','Full Art','{}'),
    ('POKEMON_TCG','CARD','ART_TREATMENT','ALTERNATE_ART','Alternate Art','{"Alt Art"}'),
    ('POKEMON_TCG','CARD','FINISH','NORMAL','Normal','{}'),
    ('POKEMON_TCG','CARD','FINISH','HOLOFOIL','Holofoil','{"Holo"}'),
    ('POKEMON_TCG','CARD','FINISH','REVERSE_HOLOFOIL','Reverse Holofoil','{"Reverse Holo"}'),
    ('POKEMON_TCG','CARD','FINISH','TEXTURED','Textured','{}');

-- Dragon Ball Super Masters official eight card types.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,source_reference
) values
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','LEADER','Leader','https://www.dbs-cardgame.com/us-en/rule/'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','BATTLE','Battle','https://www.dbs-cardgame.com/us-en/rule/'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','EXTRA','Extra','https://www.dbs-cardgame.com/us-en/rule/'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','UNISON','Unison','https://www.dbs-cardgame.com/us-en/rule/'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','Z_LEADER','Z-Leader','https://www.dbs-cardgame.com/us-en/rule/'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','Z_BATTLE','Z-Battle','https://www.dbs-cardgame.com/us-en/rule/'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','Z_EXTRA','Z-Extra','https://www.dbs-cardgame.com/us-en/rule/'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','CARD_TYPE','Z_UNISON','Z-Unison','https://www.dbs-cardgame.com/us-en/rule/');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases
) values
    ('DRAGON_BALL_SUPER_MASTERS','CARD','RARITY','COMMON','Common','{"C"}'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','RARITY','UNCOMMON','Uncommon','{"UC"}'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','RARITY','RARE','Rare','{"R"}'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','RARITY','SUPER_RARE','Super Rare','{"SR"}'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','FINISH','NORMAL','Normal','{}'),
    ('DRAGON_BALL_SUPER_MASTERS','CARD','FINISH','FOIL','Foil','{}');

-- Fusion World official database card types and rarity filters.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases,source_reference
) values
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','CARD_TYPE','LEADER','Leader','{"L"}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','CARD_TYPE','BATTLE','Battle','{}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','CARD_TYPE','EXTRA','Extra','{}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','CARD_TYPE','ENERGY_MARKER','Energy Marker','{}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','RARITY','L','Leader','{"Leader Card"}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','RARITY','C','Common','{"Common"}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','RARITY','UC','Uncommon','{"Uncommon"}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','RARITY','R','Rare','{"Rare"}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','RARITY','SR','Super Rare','{"Super Rare"}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','RARITY','SCR','Secret Rare','{"Secret Rare"}','https://www.dbs-cardgame.com/fw/en/cardlist/'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','RARITY','PR','Promo','{"Promo"}','https://www.dbs-cardgame.com/fw/en/cardlist/');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases
) values
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','ART_TREATMENT','BASE','Base / normal art','{}'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','ART_TREATMENT','ALT_ART','Alt-Art','{"Alternative Art"}'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','ART_TREATMENT','SUPER_ALT_ART','Super Alt-Art','{}'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','FINISH','NORMAL','Normal','{}'),
    ('DRAGON_BALL_SUPER_FUSION_WORLD','CARD','FINISH','HOLOFOIL','Holofoil','{"Foil"}');

-- Lorcana current official card types and collector rarities.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,source_reference
) values
    ('DISNEY_LORCANA','CARD','CARD_TYPE','CHARACTER','Character','https://www.disneylorcana.com/en-GB/news/2025/09/2025-9-card_types_examination-songs'),
    ('DISNEY_LORCANA','CARD','CARD_TYPE','ACTION','Action','https://www.disneylorcana.com/en-GB/news/2025/09/2025-9-card_types_examination-songs'),
    ('DISNEY_LORCANA','CARD','CARD_TYPE','ITEM','Item','https://www.disneylorcana.com/en-GB/news/2025/09/2025-9-card_types_examination-songs'),
    ('DISNEY_LORCANA','CARD','CARD_TYPE','LOCATION','Location','https://www.disneylorcana.com/en-GB/news/2025/09/2025-9-card_types_examination-songs'),
    ('DISNEY_LORCANA','CARD','RARITY','COMMON','Common','https://www.disneylorcana.com/en-US/product'),
    ('DISNEY_LORCANA','CARD','RARITY','UNCOMMON','Uncommon','https://www.disneylorcana.com/en-US/product'),
    ('DISNEY_LORCANA','CARD','RARITY','RARE','Rare','https://www.disneylorcana.com/en-US/product'),
    ('DISNEY_LORCANA','CARD','RARITY','SUPER_RARE','Super Rare','https://www.disneylorcana.com/en-US/product'),
    ('DISNEY_LORCANA','CARD','RARITY','LEGENDARY','Legendary','https://www.disneylorcana.com/en-US/product'),
    ('DISNEY_LORCANA','CARD','RARITY','ENCHANTED','Enchanted','https://www.disneylorcana.com/en-US/news/enchanted-reveal'),
    ('DISNEY_LORCANA','CARD','RARITY','EPIC','Epic','https://www.disneylorcana.com/en-US/news/2025/08/2025-8-stunning-new-rarities'),
    ('DISNEY_LORCANA','CARD','RARITY','ICONIC','Iconic','https://www.disneylorcana.com/en-US/news/2025/08/2025-8-stunning-new-rarities'),
    ('DISNEY_LORCANA','CARD','RARITY','ILLUSTRIOUS','Illustrious','https://www.disneylorcana.com/en-US/news/2026/08/d23-announcements');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases
) values
    ('DISNEY_LORCANA','CARD','ART_TREATMENT','BASE','Base / standard art','{}'),
    ('DISNEY_LORCANA','CARD','ART_TREATMENT','ENCHANTED','Enchanted artwork','{}'),
    ('DISNEY_LORCANA','CARD','ART_TREATMENT','ALT_ART','Alternate Art','{}'),
    ('DISNEY_LORCANA','CARD','FINISH','NON_FOIL','Non-foil','{}'),
    ('DISNEY_LORCANA','CARD','FINISH','FOIL','Foil','{}'),
    ('DISNEY_LORCANA','CARD','FINISH','RAINBOW_FOIL','Rainbow Foil','{}'),
    ('DISNEY_LORCANA','CARD','FINISH','HOT_STAMPED','Hot Stamped','{}');

-- Riftbound supports multiple types and multiple collector treatments.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,source_reference
) values
    ('RIFTBOUND','CARD','CARD_TYPE','UNIT','Unit','https://playriftbound.com/en-us/news/announcements/what-to-expect-during-preview-season/'),
    ('RIFTBOUND','CARD','CARD_TYPE','SPELL','Spell','https://playriftbound.com/en-us/news/announcements/what-to-expect-during-preview-season/'),
    ('RIFTBOUND','CARD','CARD_TYPE','GEAR','Gear','https://playriftbound.com/en-us/news/announcements/what-to-expect-during-preview-season/'),
    ('RIFTBOUND','CARD','CARD_TYPE','CHAMPION','Champion','https://playriftbound.com/en-us/news/announcements/what-to-expect-during-preview-season/'),
    ('RIFTBOUND','CARD','CARD_TYPE','LEGEND','Legend','https://playriftbound.com/en-us/news/announcements/what-to-expect-during-preview-season/'),
    ('RIFTBOUND','CARD','CARD_TYPE','BATTLEFIELD','Battlefield','https://playriftbound.com/en-us/news/announcements/what-to-expect-during-preview-season/'),
    ('RIFTBOUND','CARD','RARITY','COMMON','Common','https://playriftbound.com/en-us/news/announcements/collectability-in-riftbound-origins/'),
    ('RIFTBOUND','CARD','RARITY','UNCOMMON','Uncommon','https://playriftbound.com/en-us/news/announcements/collectability-in-riftbound-origins/'),
    ('RIFTBOUND','CARD','RARITY','RARE','Rare','https://playriftbound.com/en-us/news/announcements/collectability-in-riftbound-origins/'),
    ('RIFTBOUND','CARD','RARITY','EPIC','Epic','https://playriftbound.com/en-us/news/announcements/collectability-in-riftbound-origins/'),
    ('RIFTBOUND','CARD','RARITY','ULTIMATE','Ultimate Rare','https://playriftbound.com/en-us/news/announcements/the-unleashed-overview/');

insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases
) values
    ('RIFTBOUND','CARD','ART_TREATMENT','BASE','Base / standard art','{}'),
    ('RIFTBOUND','CARD','ART_TREATMENT','ALT_ART','Alt Art','{}'),
    ('RIFTBOUND','CARD','ART_TREATMENT','SPECIAL_ALT','Special Alt','{}'),
    ('RIFTBOUND','CARD','ART_TREATMENT','OVERNUMBER','Overnumber','{"Overnumbered"}'),
    ('RIFTBOUND','CARD','ART_TREATMENT','SIGNATURE_OVERNUMBER','Signature Overnumber','{}'),
    ('RIFTBOUND','CARD','FINISH','NON_FOIL','Non-foil','{}'),
    ('RIFTBOUND','CARD','FINISH','FOIL','Foil','{}'),
    ('RIFTBOUND','CARD','FINISH','TEXTURED','Textured / UV treatment','{}');

-- Sealed product taxonomies. Keep the registry extensible rather than hard-coding
-- these values into application enums.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name,aliases
) values
    ('POKEMON_TCG','SEALED','SEALED_TYPE','ELITE_TRAINER_BOX','Elite Trainer Box','{"ETB"}'),
    ('POKEMON_TCG','SEALED','SEALED_TYPE','BOOSTER_BOX','Booster Box','{}'),
    ('POKEMON_TCG','SEALED','SEALED_TYPE','BOOSTER_BUNDLE','Booster Bundle','{}'),
    ('POKEMON_TCG','SEALED','SEALED_TYPE','BOOSTER_PACK','Booster Pack','{}'),
    ('POKEMON_TCG','SEALED','SEALED_TYPE','COLLECTION','Collection','{}'),
    ('POKEMON_TCG','SEALED','SEALED_TYPE','TIN','Tin','{}'),
    ('POKEMON_TCG','SEALED','SEALED_TYPE','DECK','Preconstructed Deck','{}'),
    ('POKEMON_TCG','SEALED','SEALED_TYPE','CASE','Case','{}'),
    ('ONE_PIECE_CARD_GAME','SEALED','SEALED_TYPE','BOOSTER_BOX','Booster Box','{}'),
    ('ONE_PIECE_CARD_GAME','SEALED','SEALED_TYPE','BOOSTER_PACK','Booster Pack','{}'),
    ('ONE_PIECE_CARD_GAME','SEALED','SEALED_TYPE','STARTER_DECK','Starter Deck','{}'),
    ('ONE_PIECE_CARD_GAME','SEALED','SEALED_TYPE','PREMIUM_CARD_COLLECTION','Premium Card Collection','{}'),
    ('ONE_PIECE_CARD_GAME','SEALED','SEALED_TYPE','TIN_PACK_SET','Tin Pack Set','{}'),
    ('ONE_PIECE_CARD_GAME','SEALED','SEALED_TYPE','CASE','Case','{}');

-- Generic comic values. Cover codes/artists remain structured fields and can
-- grow without adding columns.
insert into tcg.taxonomy_values(
    system_code,scope_kind,dimension_code,value_code,display_name
) values
    ('MARVEL_COMICS','COMIC','COMIC_COVER_VARIANT','STANDARD','Standard Cover'),
    ('MARVEL_COMICS','COMIC','COMIC_PRINTING_CLASS','FIRST_PRINT','First Printing'),
    ('MARVEL_COMICS','COMIC','COMIC_PRINTING_CLASS','REPRINT','Reprint'),
    ('MARVEL_COMICS','COMIC','COMIC_TREATMENT','FOIL','Foil'),
    ('MARVEL_COMICS','COMIC','COMIC_TREATMENT','VIRGIN','Virgin Cover'),
    ('MARVEL_COMICS','COMIC','COMIC_TREATMENT','SKETCH','Sketch Cover'),
    ('DC_COMICS','COMIC','COMIC_COVER_VARIANT','STANDARD','Standard Cover'),
    ('DC_COMICS','COMIC','COMIC_PRINTING_CLASS','FIRST_PRINT','First Printing'),
    ('DC_COMICS','COMIC','COMIC_PRINTING_CLASS','REPRINT','Reprint'),
    ('DC_COMICS','COMIC','COMIC_TREATMENT','FOIL','Foil'),
    ('DC_COMICS','COMIC','COMIC_TREATMENT','VIRGIN','Virgin Cover'),
    ('DC_COMICS','COMIC','COMIC_TREATMENT','SKETCH','Sketch Cover');

create or replace function tcg.validate_catalogue_product_profile()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
declare
    v_product_type text;
    v_expected_type text;
begin
    select p.product_type into v_product_type
    from tcg.catalogue_products p
    where p.id=new.catalogue_id;

    if v_product_type is null then
        raise exception 'Catalogue product not found' using errcode='23503';
    end if;

    v_expected_type := case
        when v_product_type='CARD' then 'CARD'
        when v_product_type in ('SEALED','COLLECTION') then 'SEALED'
        when v_product_type='COMIC' then 'COMIC'
        when v_product_type='ACCESSORY' then 'ACCESSORY'
    end;

    if new.collectible_type <> v_expected_type then
        raise exception 'Structured collectible type does not match catalogue product type'
            using errcode='23514';
    end if;
    return new;
end;
$$;
revoke all on function tcg.validate_catalogue_product_profile() from public;
grant execute on function tcg.validate_catalogue_product_profile() to tcg_api;

create trigger catalogue_product_profiles_validate
    before insert or update on tcg.catalogue_product_profiles
    for each row execute function tcg.validate_catalogue_product_profile();

create or replace function tcg.validate_taxonomy_assignment()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
declare
    v_profile tcg.catalogue_product_profiles%rowtype;
    v_cardinality text;
begin
    select * into v_profile
    from tcg.catalogue_product_profiles
    where catalogue_id=new.catalogue_id;

    if v_profile.catalogue_id is null then
        raise exception 'Catalogue product profile is required before taxonomy assignment'
            using errcode='23503';
    end if;

    if v_profile.system_code <> new.system_code
       or v_profile.collectible_type <> new.scope_kind then
        raise exception 'Taxonomy assignment system/scope does not match product profile'
            using errcode='23514';
    end if;

    select cardinality into v_cardinality
    from tcg.taxonomy_schemas
    where system_code=new.system_code
      and scope_kind=new.scope_kind
      and dimension_code=new.dimension_code;

    if v_cardinality='SINGLE' and exists (
        select 1
        from tcg.catalogue_taxonomy_assignments a
        where a.catalogue_id=new.catalogue_id
          and a.dimension_code=new.dimension_code
          and a.id <> new.id
    ) then
        raise exception 'Taxonomy dimension permits only one value'
            using errcode='23514';
    end if;

    return new;
end;
$$;
revoke all on function tcg.validate_taxonomy_assignment() from public;
grant execute on function tcg.validate_taxonomy_assignment() to tcg_api;

create trigger catalogue_taxonomy_assignments_validate
    before insert or update on tcg.catalogue_taxonomy_assignments
    for each row execute function tcg.validate_taxonomy_assignment();

-- RLS: taxonomy definitions are read-only configuration for the app. Canonical
-- identity rows are readable to registered users but mutable only by platform admins.
alter table tcg.collectible_systems enable row level security;
alter table tcg.collectible_systems force row level security;
alter table tcg.taxonomy_schemas enable row level security;
alter table tcg.taxonomy_schemas force row level security;
alter table tcg.taxonomy_values enable row level security;
alter table tcg.taxonomy_values force row level security;
alter table tcg.catalogue_product_profiles enable row level security;
alter table tcg.catalogue_product_profiles force row level security;
alter table tcg.catalogue_taxonomy_assignments enable row level security;
alter table tcg.catalogue_taxonomy_assignments force row level security;
alter table tcg.card_gameplay_identities enable row level security;
alter table tcg.card_gameplay_identities force row level security;
alter table tcg.card_printings enable row level security;
alter table tcg.card_printings force row level security;
alter table tcg.sealed_product_details enable row level security;
alter table tcg.sealed_product_details force row level security;
alter table tcg.comic_printing_details enable row level security;
alter table tcg.comic_printing_details force row level security;
alter table tcg.provider_catalogue_mappings enable row level security;
alter table tcg.provider_catalogue_mappings force row level security;

create policy admin_access on tcg.collectible_systems
    for all to postgres using (true) with check (true);
create policy api_read on tcg.collectible_systems
    for select to tcg_api using (tcg.current_access_role() is not null);

create policy admin_access on tcg.taxonomy_schemas
    for all to postgres using (true) with check (true);
create policy api_read on tcg.taxonomy_schemas
    for select to tcg_api using (tcg.current_access_role() is not null);

create policy admin_access on tcg.taxonomy_values
    for all to postgres using (true) with check (true);
create policy api_read on tcg.taxonomy_values
    for select to tcg_api using (tcg.current_access_role() is not null);

create policy admin_access on tcg.catalogue_product_profiles
    for all to postgres using (true) with check (true);
create policy api_read on tcg.catalogue_product_profiles
    for select to tcg_api using (tcg.current_access_role() is not null);
create policy api_insert on tcg.catalogue_product_profiles
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy api_update on tcg.catalogue_product_profiles
    for update to tcg_api using (tcg.is_platform_admin()) with check (tcg.is_platform_admin());

create policy admin_access on tcg.catalogue_taxonomy_assignments
    for all to postgres using (true) with check (true);
create policy api_read on tcg.catalogue_taxonomy_assignments
    for select to tcg_api using (tcg.current_access_role() is not null);
create policy api_insert on tcg.catalogue_taxonomy_assignments
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy api_update on tcg.catalogue_taxonomy_assignments
    for update to tcg_api using (tcg.is_platform_admin()) with check (tcg.is_platform_admin());

create policy admin_access on tcg.card_gameplay_identities
    for all to postgres using (true) with check (true);
create policy api_read on tcg.card_gameplay_identities
    for select to tcg_api using (tcg.current_access_role() is not null);
create policy api_insert on tcg.card_gameplay_identities
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy api_update on tcg.card_gameplay_identities
    for update to tcg_api using (tcg.is_platform_admin()) with check (tcg.is_platform_admin());

create policy admin_access on tcg.card_printings
    for all to postgres using (true) with check (true);
create policy api_read on tcg.card_printings
    for select to tcg_api using (tcg.current_access_role() is not null);
create policy api_insert on tcg.card_printings
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy api_update on tcg.card_printings
    for update to tcg_api using (tcg.is_platform_admin()) with check (tcg.is_platform_admin());

create policy admin_access on tcg.sealed_product_details
    for all to postgres using (true) with check (true);
create policy api_read on tcg.sealed_product_details
    for select to tcg_api using (tcg.current_access_role() is not null);
create policy api_insert on tcg.sealed_product_details
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy api_update on tcg.sealed_product_details
    for update to tcg_api using (tcg.is_platform_admin()) with check (tcg.is_platform_admin());

create policy admin_access on tcg.comic_printing_details
    for all to postgres using (true) with check (true);
create policy api_read on tcg.comic_printing_details
    for select to tcg_api using (tcg.current_access_role() is not null);
create policy api_insert on tcg.comic_printing_details
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy api_update on tcg.comic_printing_details
    for update to tcg_api using (tcg.is_platform_admin()) with check (tcg.is_platform_admin());

create policy admin_access on tcg.provider_catalogue_mappings
    for all to postgres using (true) with check (true);
create policy api_read on tcg.provider_catalogue_mappings
    for select to tcg_api using (tcg.current_access_role() is not null);
create policy api_insert on tcg.provider_catalogue_mappings
    for insert to tcg_api with check (tcg.is_platform_admin());
create policy api_update on tcg.provider_catalogue_mappings
    for update to tcg_api using (tcg.is_platform_admin()) with check (tcg.is_platform_admin());

revoke all on
    tcg.collectible_systems,
    tcg.taxonomy_schemas,
    tcg.taxonomy_values,
    tcg.catalogue_product_profiles,
    tcg.catalogue_taxonomy_assignments,
    tcg.card_gameplay_identities,
    tcg.card_printings,
    tcg.sealed_product_details,
    tcg.comic_printing_details,
    tcg.provider_catalogue_mappings
from public, anon, authenticated;

grant select on tcg.collectible_systems,tcg.taxonomy_schemas,tcg.taxonomy_values to tcg_api;
grant select,insert,update on
    tcg.catalogue_product_profiles,
    tcg.catalogue_taxonomy_assignments,
    tcg.card_gameplay_identities,
    tcg.card_printings,
    tcg.sealed_product_details,
    tcg.comic_printing_details,
    tcg.provider_catalogue_mappings
to tcg_api;
revoke delete on
    tcg.collectible_systems,
    tcg.taxonomy_schemas,
    tcg.taxonomy_values,
    tcg.catalogue_product_profiles,
    tcg.catalogue_taxonomy_assignments,
    tcg.card_gameplay_identities,
    tcg.card_printings,
    tcg.sealed_product_details,
    tcg.comic_printing_details,
    tcg.provider_catalogue_mappings
from tcg_api;

create or replace function tcg.audit_collectible_identity_change()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
    v_row jsonb;
    v_entity_id uuid;
begin
    v_row := case when tg_op='DELETE' then to_jsonb(old) else to_jsonb(new) end;
    v_entity_id := coalesce(
        nullif(v_row->>'id','')::uuid,
        nullif(v_row->>'catalogue_id','')::uuid,
        nullif(v_row->>'gameplay_identity_id','')::uuid
    );

    insert into tcg.audit_events(
        actor,request_id,action,entity_type,entity_id,old_values,new_values
    ) values (
        coalesce(nullif(current_setting('tcg.user_id',true),''),session_user::text),
        nullif(current_setting('tcg.request_id',true),''),
        tg_op,
        tg_table_name,
        v_entity_id,
        case when tg_op='INSERT' then null else to_jsonb(old) end,
        case when tg_op='DELETE' then null else to_jsonb(new) end
    );
    return null;
end;
$$;
revoke all on function tcg.audit_collectible_identity_change() from public;

create trigger catalogue_product_profiles_audit
    after insert or update or delete on tcg.catalogue_product_profiles
    for each row execute function tcg.audit_collectible_identity_change();
create trigger catalogue_taxonomy_assignments_audit
    after insert or update or delete on tcg.catalogue_taxonomy_assignments
    for each row execute function tcg.audit_collectible_identity_change();
create trigger card_gameplay_identities_audit
    after insert or update or delete on tcg.card_gameplay_identities
    for each row execute function tcg.audit_collectible_identity_change();
create trigger card_printings_audit
    after insert or update or delete on tcg.card_printings
    for each row execute function tcg.audit_collectible_identity_change();
create trigger sealed_product_details_audit
    after insert or update or delete on tcg.sealed_product_details
    for each row execute function tcg.audit_collectible_identity_change();
create trigger comic_printing_details_audit
    after insert or update or delete on tcg.comic_printing_details
    for each row execute function tcg.audit_collectible_identity_change();
create trigger provider_catalogue_mappings_audit
    after insert or update or delete on tcg.provider_catalogue_mappings
    for each row execute function tcg.audit_collectible_identity_change();

-- Backfill current catalogue without claiming that legacy rows are already exact.
insert into tcg.catalogue_product_profiles(
    catalogue_id,system_code,collectible_type,identity_status,attributes
)
select
    p.id,
    case p.game
        when 'Pokemon' then 'POKEMON_TCG'
        when 'One Piece' then 'ONE_PIECE_CARD_GAME'
        when 'Dragon Ball Super' then 'DRAGON_BALL_SUPER_MASTERS'
        when 'Dragon Ball Super Fusion World' then 'DRAGON_BALL_SUPER_FUSION_WORLD'
    end,
    case when p.product_type='CARD' then 'CARD' else 'SEALED' end,
    'LEGACY_UNREVIEWED',
    jsonb_build_object(
        'legacy_product_type',p.product_type,
        'legacy_game',p.game,
        'legacy_set_name',p.set_name,
        'legacy_variant',p.variant,
        'legacy_rarity',p.rarity
    )
from tcg.catalogue_products p
where p.game in (
    'Pokemon','One Piece','Dragon Ball Super','Dragon Ball Super Fusion World'
);

with keyed as (
    select
        p.*,
        pr.system_code,
        case
            when pr.system_code='POKEMON_TCG'
                then lower(btrim(p.set_name)) || '|' || lower(btrim(coalesce(p.card_number,'')))
            when nullif(btrim(coalesce(p.card_number,'')),'') is not null
                then lower(btrim(p.card_number))
            else 'legacy-catalogue:' || p.id::text
        end as native_identity_key
    from tcg.catalogue_products p
    join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
    where pr.collectible_type='CARD'
),
grouped as (
    select
        system_code,
        native_identity_key,
        (array_agg(name order by length(name),name))[1] as canonical_name,
        (array_agg(card_number order by card_number nulls last))[1] as card_number,
        jsonb_build_object(
            'legacy_names',to_jsonb(array_agg(distinct name order by name)),
            'legacy_sets',to_jsonb(array_agg(distinct set_name order by set_name))
        ) as attributes
    from keyed
    group by system_code,native_identity_key
)
insert into tcg.card_gameplay_identities(
    system_code,native_identity_key,canonical_name,card_number,identity_status,attributes
)
select system_code,native_identity_key,canonical_name,card_number,'LEGACY_UNREVIEWED',attributes
from grouped;

insert into tcg.card_printings(
    catalogue_id,gameplay_identity_id,system_code,printing_key,identity_status,attributes
)
select
    p.id,
    g.id,
    pr.system_code,
    'legacy:' || p.id::text,
    case
        when nullif(btrim(coalesce(p.card_number,'')),'') is null
            then 'NEEDS_REVIEW'
        else 'LEGACY_UNREVIEWED'
    end,
    jsonb_build_object(
        'legacy_identity_key',p.identity_key,
        'legacy_variant',p.variant,
        'legacy_rarity',p.rarity,
        'legacy_language',p.language
    )
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
join tcg.card_gameplay_identities g
  on g.system_code=pr.system_code
 and g.native_identity_key=case
        when pr.system_code='POKEMON_TCG'
            then lower(btrim(p.set_name)) || '|' || lower(btrim(coalesce(p.card_number,'')))
        when nullif(btrim(coalesce(p.card_number,'')),'') is not null
            then lower(btrim(p.card_number))
        else 'legacy-catalogue:' || p.id::text
    end
where pr.collectible_type='CARD';

insert into tcg.sealed_product_details(
    catalogue_id,system_code,identity_status,attributes
)
select
    p.id,pr.system_code,'LEGACY_UNREVIEWED',
    jsonb_build_object('legacy_name',p.name,'legacy_set_name',p.set_name)
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
where pr.collectible_type='SEALED';

-- Backfill legacy finish fields as unverified structured evidence.
insert into tcg.catalogue_taxonomy_assignments(
    catalogue_id,system_code,scope_kind,dimension_code,value_code,is_primary,
    verification_status,source_kind,metadata
)
select
    p.id,pr.system_code,'CARD','FINISH',
    case
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.variant))='holofoil' then 'HOLOFOIL'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.variant))='reverse holofoil' then 'REVERSE_HOLOFOIL'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.variant))='normal' then 'NORMAL'
        when pr.system_code='ONE_PIECE_CARD_GAME' and lower(btrim(p.variant))='foil' then 'FOIL'
        when pr.system_code='ONE_PIECE_CARD_GAME' and lower(btrim(p.variant))='normal' then 'NORMAL'
        when pr.system_code='DRAGON_BALL_SUPER_MASTERS' and lower(btrim(p.variant))='foil' then 'FOIL'
        when pr.system_code='DRAGON_BALL_SUPER_MASTERS' and lower(btrim(p.variant))='normal' then 'NORMAL'
        when pr.system_code='DRAGON_BALL_SUPER_FUSION_WORLD' and lower(btrim(p.variant))='holofoil' then 'HOLOFOIL'
        when pr.system_code='DRAGON_BALL_SUPER_FUSION_WORLD' and lower(btrim(p.variant))='normal' then 'NORMAL'
    end,
    true,'MIGRATED_UNVERIFIED','LEGACY_IMPORT',
    jsonb_build_object('legacy_variant',p.variant)
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
where pr.collectible_type='CARD'
  and (
    (pr.system_code='POKEMON_TCG' and lower(btrim(p.variant)) in ('holofoil','reverse holofoil','normal'))
    or (pr.system_code='ONE_PIECE_CARD_GAME' and lower(btrim(p.variant)) in ('foil','normal'))
    or (pr.system_code='DRAGON_BALL_SUPER_MASTERS' and lower(btrim(p.variant)) in ('foil','normal'))
    or (pr.system_code='DRAGON_BALL_SUPER_FUSION_WORLD' and lower(btrim(p.variant)) in ('holofoil','normal'))
  );

-- Backfill current rarity strings only where they map cleanly to a registered value.
insert into tcg.catalogue_taxonomy_assignments(
    catalogue_id,system_code,scope_kind,dimension_code,value_code,is_primary,
    verification_status,source_kind,metadata
)
select p.id,pr.system_code,'CARD','RARITY',mapped.value_code,true,
       'MIGRATED_UNVERIFIED','LEGACY_IMPORT',
       jsonb_build_object('legacy_rarity',p.rarity)
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
cross join lateral (
    select case
        when pr.system_code='ONE_PIECE_CARD_GAME' and p.rarity in ('C','UC','R','SR','SEC','L') then p.rarity
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='common' then 'COMMON'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='uncommon' then 'UNCOMMON'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='rare' then 'RARE'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='holo rare' then 'RARE_HOLO'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='double rare' then 'DOUBLE_RARE'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='ultra rare' then 'ULTRA_RARE'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='art rare' then 'ILLUSTRATION_RARE'
        when pr.system_code='POKEMON_TCG' and lower(btrim(p.rarity))='mega attack rare' then 'MEGA_ATTACK_RARE'
        when pr.system_code='DRAGON_BALL_SUPER_MASTERS' and lower(btrim(p.rarity))='common' then 'COMMON'
        when pr.system_code='DRAGON_BALL_SUPER_MASTERS' and lower(btrim(p.rarity))='uncommon' then 'UNCOMMON'
        when pr.system_code='DRAGON_BALL_SUPER_MASTERS' and lower(btrim(p.rarity))='rare' then 'RARE'
        when pr.system_code='DRAGON_BALL_SUPER_MASTERS' and lower(btrim(p.rarity))='super rare' then 'SUPER_RARE'
        when pr.system_code='DRAGON_BALL_SUPER_FUSION_WORLD' and lower(btrim(p.rarity))='uncommon' then 'UC'
        when pr.system_code='DRAGON_BALL_SUPER_FUSION_WORLD' and lower(btrim(p.rarity))='super rare' then 'SR'
        when pr.system_code='DRAGON_BALL_SUPER_FUSION_WORLD' and lower(btrim(p.rarity))='promo' then 'PR'
    end as value_code
) mapped
where pr.collectible_type='CARD'
  and mapped.value_code is not null;

-- Promo and explicit One Piece collector labels are classifications, not silently
-- folded into rarity.
insert into tcg.catalogue_taxonomy_assignments(
    catalogue_id,system_code,scope_kind,dimension_code,value_code,is_primary,
    verification_status,source_kind,metadata
)
select p.id,pr.system_code,'CARD','SPECIAL_CLASSIFICATION',
       case
         when lower(btrim(p.rarity)) in ('pr','promo') then 'PROMO'
         when p.name ~* '[(]SP[)]' then 'SP'
       end,
       false,'MIGRATED_UNVERIFIED','LEGACY_IMPORT',
       jsonb_build_object('legacy_rarity',p.rarity,'legacy_name',p.name)
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
where pr.system_code='ONE_PIECE_CARD_GAME'
  and (lower(btrim(p.rarity)) in ('pr','promo') or p.name ~* '[(]SP[)]');

-- Explicit artwork words are useful evidence but remain unverified until provider
-- and visual confirmation agree.
insert into tcg.catalogue_taxonomy_assignments(
    catalogue_id,system_code,scope_kind,dimension_code,value_code,is_primary,
    verification_status,source_kind,metadata
)
select p.id,pr.system_code,'CARD','ART_TREATMENT',
       case
         when p.name ~* '[(]Parallel[)]' then 'PARALLEL'
         when p.name ~* 'Alternate Art|Alt Art' then 'ALTERNATE_ART'
       end,
       true,'MIGRATED_UNVERIFIED','LEGACY_IMPORT',
       jsonb_build_object('legacy_name',p.name)
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
where pr.system_code='ONE_PIECE_CARD_GAME'
  and (p.name ~* '[(]Parallel[)]' or p.name ~* 'Alternate Art|Alt Art');

-- The existing DON!! row is known to be a card category, not a rarity.
insert into tcg.catalogue_taxonomy_assignments(
    catalogue_id,system_code,scope_kind,dimension_code,value_code,is_primary,
    verification_status,source_kind,metadata
)
select p.id,pr.system_code,'CARD','CARD_TYPE','DON',true,
       'MIGRATED_UNVERIFIED','SYSTEM_RULE',
       jsonb_build_object('legacy_rarity',p.rarity)
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
where pr.system_code='ONE_PIECE_CARD_GAME'
  and p.rarity='DON!!';

-- Current One Piece sealed collection rows.
insert into tcg.catalogue_taxonomy_assignments(
    catalogue_id,system_code,scope_kind,dimension_code,value_code,is_primary,
    verification_status,source_kind,metadata
)
select p.id,pr.system_code,'SEALED','SEALED_TYPE',
       case
         when p.name ilike '%Tin Pack Set%' then 'TIN_PACK_SET'
         when p.name ilike '%Premium Card Collection%' then 'PREMIUM_CARD_COLLECTION'
       end,
       true,'MIGRATED_UNVERIFIED','LEGACY_IMPORT',
       jsonb_build_object('legacy_name',p.name)
from tcg.catalogue_products p
join tcg.catalogue_product_profiles pr on pr.catalogue_id=p.id
where pr.system_code='ONE_PIECE_CARD_GAME'
  and pr.collectible_type='SEALED'
  and (p.name ilike '%Tin Pack Set%' or p.name ilike '%Premium Card Collection%');

-- Existing free-provider mappings become reviewable catalogue evidence. Human
-- media approval does not silently promote them to canonical identity verification.
insert into tcg.provider_catalogue_mappings(
    catalogue_id,system_code,source_provider,provider_entity_type,provider_id,
    provider_variant_key,provider_language,source_reference,match_status,
    verification_basis,confidence,metadata
)
select distinct on (m.source_provider,m.provider_asset_id,coalesce(m.media_language,''))
    m.catalogue_id,
    pr.system_code,
    m.source_provider,
    'CARD_PRINTING',
    m.provider_asset_id,
    coalesce(m.media_variant,''),
    coalesce(m.media_language,''),
    m.source_reference,
    'REVIEW',
    'DETERMINISTIC_EXACT',
    1.0000,
    jsonb_build_object('media_asset_id',m.id,'media_approval_status',m.approval_status)
from tcg.media_assets m
join tcg.catalogue_product_profiles pr on pr.catalogue_id=m.catalogue_id
where m.source_provider in ('TCGdex','Punk Records')
  and m.provider_asset_id is not null
order by m.source_provider,m.provider_asset_id,coalesce(m.media_language,''),m.created_at;

commit;
