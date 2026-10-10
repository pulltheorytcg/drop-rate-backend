begin;

-- Display-only repair for the exact pre-existing Japanese single pack.
-- Bandai's current product page links this pack image separately from its box:
-- https://www.onepiece-cardgame.com/products/boosters/op17/
-- This does not insert/approve media, alter physical identity, or publish stock.
update tcg.catalogue_product_profiles pr
set attributes=pr.attributes || jsonb_build_object(
      'inventory_reference_image_url','https://www.onepiece-cardgame.com/products/boosters/op17/images/others/product_pack.webp',
      'inventory_reference_source_url','https://www.onepiece-cardgame.com/products/boosters/op17/',
      'inventory_reference_identity',jsonb_build_object(
          'name',p.name,'set_name',p.set_name,'variant',p.variant,
          'language',p.language,'product_type',p.product_type)
    ),version=pr.version+1,updated_at=clock_timestamp()
from tcg.catalogue_products p
where pr.catalogue_id=p.id
  and p.identity_key='sealed:v1:one_piece_card_game:op17:booster_pack:jp'
  and p.product_type='SEALED' and p.game='One Piece' and p.language='Japanese'
  and p.name='Booster Pack: World''s Strongest Warriors [OP-17]'
  and p.set_name='World''s Strongest Warriors [OP-17]' and p.variant=''
  and pr.system_code='ONE_PIECE_CARD_GAME' and pr.identity_status='VERIFIED'
  and pr.attributes->>'inventory_reference_image_url' is distinct from
      'https://www.onepiece-cardgame.com/products/boosters/op17/images/others/product_pack.webp';

commit;
