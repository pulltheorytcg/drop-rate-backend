-- In-app reference-card image cache, separate from licensed/approved storefront
-- media. This table does not claim copyright ownership or approve a Shopify
-- listing. The source reference remains authoritative for identity and URL.
-- No customer scans, private inventory, pricing or account data are stored.
create table tcg.reference_image_mirrors (
    provider text not null,
    system_code text not null,
    language text not null,
    provider_id text not null,
    source_url text not null check (source_url ~ '^https://[^[:space:]]+$'),
    object_key text check (
        object_key is null or object_key ~ '^[a-zA-Z0-9_-]+/private-media/[0-9a-f]{64}\.webp$'
    ),
    content_sha256 text check (
        content_sha256 is null or content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    size_bytes integer check (size_bytes is null or size_bytes between 1 and 10000000),
    status text not null check (status in ('VERIFIED','RETRY')),
    failure_count integer not null default 0 check (failure_count between 0 and 1000000),
    next_retry_at timestamptz,
    last_error_code text,
    verified_at timestamptz,
    updated_at timestamptz not null default now(),
    primary key (provider,system_code,language,provider_id),
    constraint reference_image_mirror_shape check (
        (status='VERIFIED' and object_key is not null and content_sha256 is not null
         and size_bytes is not null and verified_at is not null
         and right(object_key,69)=content_sha256||'.webp'
         and next_retry_at is null and last_error_code is null)
        or (status='RETRY' and object_key is null and content_sha256 is null
            and size_bytes is null and verified_at is null
            and next_retry_at is not null and last_error_code is not null)
    )
);

comment on table tcg.reference_image_mirrors is
    'Private exact-print reference cache; never promotes provider imagery to approved sale/Shopify media.';

alter table tcg.reference_image_mirrors enable row level security;
alter table tcg.reference_image_mirrors force row level security;
revoke all on table tcg.reference_image_mirrors from public,anon,authenticated;

-- Both a source identity match and official-host reference are required.
-- This guards direct database writes independently of the application URL
-- validator; it is not a legal licence assertion for the source artwork.
-- Backend-only reads include stale-source rows so safe idempotent upserts can
-- replace them. Public delivery joins the current reference and exact URL.
create policy reference_image_mirrors_select on tcg.reference_image_mirrors
    for select to tcg_api using (true);

create policy reference_image_mirrors_insert on tcg.reference_image_mirrors
    for insert to tcg_api with check (exists (
        select 1 from tcg.reference_cards r
        where (r.provider,r.system_code,r.language,r.provider_id)=
              (reference_image_mirrors.provider,reference_image_mirrors.system_code,
               reference_image_mirrors.language,reference_image_mirrors.provider_id)
          and r.image_url=reference_image_mirrors.source_url
          and ((r.provider='TCGdex' and r.system_code='POKEMON_TCG'
                and split_part(reference_image_mirrors.source_url,'/',3)='assets.tcgdex.net')
            or (r.provider='Bandai Official'
                and r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
                and split_part(reference_image_mirrors.source_url,'/',3)='www.dbs-cardgame.com')
            or (r.provider in ('Punk Records','Bandai Official')
                and r.system_code='ONE_PIECE_CARD_GAME'
                and split_part(reference_image_mirrors.source_url,'/',3) in
                    ('en.onepiece-cardgame.com','www.onepiece-cardgame.com')))
    ));

create policy reference_image_mirrors_update on tcg.reference_image_mirrors
    for update to tcg_api using (true)
    with check (exists (
        select 1 from tcg.reference_cards r
        where (r.provider,r.system_code,r.language,r.provider_id)=
              (reference_image_mirrors.provider,reference_image_mirrors.system_code,
               reference_image_mirrors.language,reference_image_mirrors.provider_id)
          and r.image_url=reference_image_mirrors.source_url
          and ((r.provider='TCGdex' and r.system_code='POKEMON_TCG'
                and split_part(reference_image_mirrors.source_url,'/',3)='assets.tcgdex.net')
            or (r.provider='Bandai Official'
                and r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
                and split_part(reference_image_mirrors.source_url,'/',3)='www.dbs-cardgame.com')
            or (r.provider in ('Punk Records','Bandai Official')
                and r.system_code='ONE_PIECE_CARD_GAME'
                and split_part(reference_image_mirrors.source_url,'/',3) in
                    ('en.onepiece-cardgame.com','www.onepiece-cardgame.com')))
    ));

grant select,insert,update on tcg.reference_image_mirrors to tcg_api;
revoke delete on tcg.reference_image_mirrors from tcg_api;
