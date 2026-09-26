-- Prevent duplicate live media sides as batch founder uploads are introduced.
-- Rejected or Shopify-failed assets may be replaced deliberately.

create unique index media_assets_canonical_live_side_uidx
    on tcg.media_assets(owner_id,catalogue_id,side)
    where scope='CANONICAL_CARD'
      and approval_status <> 'REJECTED'
      and shopify_file_status <> 'FAILED';

create unique index media_assets_inventory_live_side_uidx
    on tcg.media_assets(owner_id,inventory_id,side)
    where scope='INVENTORY_ITEM'
      and approval_status <> 'REJECTED'
      and shopify_file_status <> 'FAILED';
