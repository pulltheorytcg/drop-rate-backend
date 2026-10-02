# Collector hub redesign and registration handoff repair

## Problem and evidence

The previous shared entry did not cover registration. Runtime request logs on 2 October 2026 showed successful `/api/v1/owner-self-register` followed immediately by `/owner` → `/app`, then a second password sign-in. Both invitation scripts still wrote legacy session keys; `hub-session.js` deleted those keys without migration. The existing-account control on public registration also opened another login form and repeated registration.

The shared shell additionally replaced the approved Seller Hub lockup with the older logo and an invented wordmark. The previous visual changes did not give the seller home the anime/TCG identity requested.

## Changes

- Registration and both invitation flows save through the same tab-scoped session helper. A single unambiguous legacy session migrates forward; conflicting accounts never get guessed. The existing server permission check still decides which hub can open.
- Public registration's existing-account link goes to `/app`. Invitation acceptance keeps its acknowledgement flow. The shared entry has an explicit Create account link.
- Restored the approved transparent Seller Hub artwork, with its aspect ratio preserved. Founder branding uses the existing Founder HQ artwork.
- Original illustrated home and sign-in, navy/cream/turquoise/gold palette, four prominent game destinations, optional local-only colour themes, collection overview and reorganised balance/payout cards. Both roles receive the collector identity; existing role-scoped tools remain.
- One Piece, Pokémon, Naruto Kayou and Dragon Ball Masters home tiles open the matching catalogue with ownership filters cleared. Search retains all supported game systems, including Naruto Bandai and Dragon Ball Fusion World. Direct game entry immediately shows loading placeholders.
- Responsive sidebar/bottom navigation, keyboard focus states and reduced-motion handling. Scanner code and financial/permission contracts are unchanged.

## Artwork

`backend/app/static/brand-assets/seller-hub-approved.webp` is a format conversion of the previously approved `drop-rate-seller-hub-approved.png` from the Drop Rate Shopify CDN; no creative changes were made. Existing game logos retain their sources in `title-art/sources.json`.

`backend/app/static/brand-assets/collector-worlds.webp` was created with the built-in image-generation tool and encoded for the web. It is decorative original artwork, never an inventory/product image.

Generation prompt: “Wide cinematic illustration background for Drop Rate trading-card collector dashboard. Original premium anime/manga key art, landscape 3:2. Midnight navy sky and cyan ocean waves, swirling turquoise energy, golden lightning, cherry-red accents. Right two-thirds: three dynamic floating collectible card backs with original compass/star emblems, red ribbon, golden sparks; small pirate sailing ship, ninja shuriken and scroll, orange star orb and yellow lightning. Original symbols only, no franchise characters/logos or text. Left third quiet deep navy for a separate website headline. Bold ink outlines, cel shading, halftone texture, manga speed lines. No UI, fake product cards/card faces or watermark.”

## Validation and limits

- Six executable journey regressions cover self-registration and invited seller handoff into a fresh hub document, founder invitation session writing, public existing-account routing, single-session migration and conflicting legacy accounts.
- Existing backend and dashboard suites remain release gates. Visual fixtures cover both roles at desktop 1440px, phone 390px and small phone 320px, including direct game destinations, unowned products, colour themes, Search and More.
- Fixtures use demo data and mocked authentication. Actual account credentials were not used. Production verification checks published assets, readiness and public entry rendering; it does not claim real-device authenticated acceptance.
- Application rollback target: `5743a9406952875fe486fa233f76d13336a6a719`. No schema, inventory, account, payout or permission mutations are included.
