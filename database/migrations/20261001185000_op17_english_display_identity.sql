begin;

-- English-readable display identity for the verified Japanese OP-17 booster pack.
update tcg.catalogue_products
set name='Booster Pack: World''s Strongest Warriors [OP-17]',
    set_name='World''s Strongest Warriors [OP-17]'
where identity_key='sealed:v1:one_piece_card_game:op17:booster_pack:jp';

update tcg.catalogue_product_profiles pr
set attributes = pr.attributes || jsonb_build_object(
        'display_name_en','Booster Pack: World''s Strongest Warriors [OP-17]',
        'set_name_en','World''s Strongest Warriors [OP-17]'
    ),
    updated_at=clock_timestamp(),
    version=pr.version+1
from tcg.catalogue_products p
where p.id=pr.catalogue_id
  and p.identity_key='sealed:v1:one_piece_card_game:op17:booster_pack:jp';

update tcg.sealed_product_details sd
set attributes = sd.attributes || jsonb_build_object(
        'display_name_en','Booster Pack: World''s Strongest Warriors [OP-17]',
        'set_name_en','World''s Strongest Warriors [OP-17]'
    ),
    updated_at=clock_timestamp(),
    version=sd.version+1
from tcg.catalogue_products p
where p.id=sd.catalogue_id
  and p.identity_key='sealed:v1:one_piece_card_game:op17:booster_pack:jp';

commit;
