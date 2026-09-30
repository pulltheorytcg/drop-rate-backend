begin;

alter table tcg.action_required_items
  drop constraint action_required_items_category_check;

alter table tcg.action_required_items
  add constraint action_required_items_category_check
  check (
    category = any (
      array[
        'IDENTITY'::text,
        'MEDIA'::text,
        'PRICING'::text,
        'IMPORT'::text,
        'SHOPIFY'::text,
        'CHANNEL'::text,
        'SETTLEMENT'::text,
        'OWNERSHIP'::text,
        'DUPLICATE'::text,
        'CUSTOMER_DISPUTE'::text,
        'AUTOMATION'::text
      ]
    )
  );

commit;
