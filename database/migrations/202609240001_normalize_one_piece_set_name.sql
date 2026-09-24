-- Normalize the One Piece OP-13 set label without changing catalogue identity.
-- This updates display text only; canonical product IDs and inventory references remain unchanged.

update tcg.catalogue_products
set set_name = 'Carrying On His Will'
where game = 'One Piece'
  and set_name = 'Carrying on His Will';
