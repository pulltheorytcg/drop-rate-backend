-- Extend the authorized private reference cache to the remaining existing
-- catalogue hosts. Exact source-row equality, RLS and media separation remain.
alter policy reference_image_mirrors_insert on tcg.reference_image_mirrors
    to tcg_api with check (exists (
        select 1 from tcg.reference_cards r
        where (r.provider,r.system_code,r.language,r.provider_id)=
              (reference_image_mirrors.provider,reference_image_mirrors.system_code,
               reference_image_mirrors.language,reference_image_mirrors.provider_id)
          and r.image_url=reference_image_mirrors.source_url
          and ((r.provider='TCGdex' and r.system_code='POKEMON_TCG'
                and (split_part(reference_image_mirrors.source_url,'/',3)='assets.tcgdex.net'
                  or reference_image_mirrors.source_url ~ '^https://cardtrader[.]com/uploads/blueprints/image/[0-9]+/[A-Za-z0-9_.-]+[.](png|webp|jpg|jpeg)$'))
            or (r.provider='Naruto Card Game Archive'
                and ((r.system_code='NARUTO_BANDAI_LEGACY'
                      and reference_image_mirrors.source_url ~ '^https://narutocardgame[.]gg/images/classic/[A-Za-z0-9_.-]+[.](png|webp|jpg|jpeg)$')
                  or (r.system_code='NARUTO_KAYOU'
                      and reference_image_mirrors.source_url ~ '^https://narutocardgame[.]gg/images/kayou/[A-Za-z0-9_.-]+[.](png|webp|jpg|jpeg)$')))
            or (r.provider='Bandai Official'
                and r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
                and split_part(reference_image_mirrors.source_url,'/',3)='www.dbs-cardgame.com')
            or (r.provider in ('Punk Records','Bandai Official')
                and r.system_code='ONE_PIECE_CARD_GAME'
                and split_part(reference_image_mirrors.source_url,'/',3) in
                    ('en.onepiece-cardgame.com','www.onepiece-cardgame.com')))
    ));

alter policy reference_image_mirrors_update on tcg.reference_image_mirrors
    to tcg_api using (true)
    with check (exists (
        select 1 from tcg.reference_cards r
        where (r.provider,r.system_code,r.language,r.provider_id)=
              (reference_image_mirrors.provider,reference_image_mirrors.system_code,
               reference_image_mirrors.language,reference_image_mirrors.provider_id)
          and r.image_url=reference_image_mirrors.source_url
          and ((r.provider='TCGdex' and r.system_code='POKEMON_TCG'
                and (split_part(reference_image_mirrors.source_url,'/',3)='assets.tcgdex.net'
                  or reference_image_mirrors.source_url ~ '^https://cardtrader[.]com/uploads/blueprints/image/[0-9]+/[A-Za-z0-9_.-]+[.](png|webp|jpg|jpeg)$'))
            or (r.provider='Naruto Card Game Archive'
                and ((r.system_code='NARUTO_BANDAI_LEGACY'
                      and reference_image_mirrors.source_url ~ '^https://narutocardgame[.]gg/images/classic/[A-Za-z0-9_.-]+[.](png|webp|jpg|jpeg)$')
                  or (r.system_code='NARUTO_KAYOU'
                      and reference_image_mirrors.source_url ~ '^https://narutocardgame[.]gg/images/kayou/[A-Za-z0-9_.-]+[.](png|webp|jpg|jpeg)$')))
            or (r.provider='Bandai Official'
                and r.system_code in ('DRAGON_BALL_SUPER_MASTERS','DRAGON_BALL_SUPER_FUSION_WORLD')
                and split_part(reference_image_mirrors.source_url,'/',3)='www.dbs-cardgame.com')
            or (r.provider in ('Punk Records','Bandai Official')
                and r.system_code='ONE_PIECE_CARD_GAME'
                and split_part(reference_image_mirrors.source_url,'/',3) in
                    ('en.onepiece-cardgame.com','www.onepiece-cardgame.com')))
    ));
