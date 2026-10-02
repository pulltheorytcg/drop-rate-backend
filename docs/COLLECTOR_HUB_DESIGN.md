# Collector hub redesign and registration handoff repair

## Problem and evidence

The previous shared entry did not cover registration. Runtime request logs on 2 October 2026 showed successful `/api/v1/owner-self-register` followed immediately by `/owner` → `/app`, then a second password sign-in. Both invitation scripts still wrote legacy session keys; `hub-session.js` deleted those keys without migration. The existing-account control on public registration also opened another login form and repeated registration.

The shared shell additionally replaced the approved Seller Hub lockup with the older logo and an invented wordmark. The previous visual changes did not give the seller home the anime/TCG identity requested.

## Changes

- Registration and both invitation flows save through the same tab-scoped session helper. A single unambiguous legacy session migrates forward; conflicting accounts never get guessed. The existing server permission check still decides which hub can open.
- Public registration's existing-account link goes to `/app`. Invitation acceptance keeps its acknowledgement flow. The shared entry has an explicit Create account link.
- Restored the approved transparent Seller Hub artwork, with its aspect ratio preserved. Founder branding uses the existing Founder HQ artwork.
- Grail-card home and illustrated sign-in, navy/cream/turquoise/gold palette, four prominent game destinations, optional local-only colour themes, collection overview and reorganised balance/payout cards. Both roles receive the collector identity; existing role-scoped tools remain.
- One Piece, Pokémon, Naruto and Dragon Ball Masters home tiles open the matching catalogue with ownership filters cleared. Naruto combines Kayou and Bandai Legacy in one browse destination; Search retains Dragon Ball Fusion World separately. Direct game entry immediately shows loading placeholders.
- Responsive sidebar/bottom navigation, keyboard focus states and reduced-motion handling. Scanner code and financial/permission contracts are unchanged.

## Artwork

`backend/app/static/brand-assets/seller-hub-approved.webp` is a format conversion of the previously approved `drop-rate-seller-hub-approved.png` from the Drop Rate Shopify CDN; no creative changes were made. Existing game logos retain their sources in `title-art/sources.json`.

`backend/app/static/brand-assets/collector-worlds.webp` was created with the built-in image-generation tool and encoded for the web. It is decorative original artwork used on sign-in, never an inventory/product image. The home hero now uses verified card references instead.

Generation prompt: “Wide cinematic illustration background for Drop Rate trading-card collector dashboard. Original premium anime/manga key art, landscape 3:2. Midnight navy sky and cyan ocean waves, swirling turquoise energy, golden lightning, cherry-red accents. Right two-thirds: three dynamic floating collectible card backs with original compass/star emblems, red ribbon, golden sparks; small pirate sailing ship, ninja shuriken and scroll, orange star orb and yellow lightning. Original symbols only, no franchise characters/logos or text. Left third quiet deep navy for a separate website headline. Bold ink outlines, cel shading, halftone texture, manga speed lines. No UI, fake product cards/card faces or watermark.”

## Validation and limits

- Six executable journey regressions cover self-registration and invited seller handoff into a fresh hub document, founder invitation session writing, public existing-account routing, single-session migration and conflicting legacy accounts.
- Existing backend and dashboard suites remain release gates. Visual fixtures cover both roles at desktop 1440px, phone 390px and small phone 320px, including direct game destinations, unowned products, colour themes, Search and More.
- Fixtures use demo data and mocked authentication. Actual account credentials were not used. Production verification checks published assets, readiness and public entry rendering; it does not claim real-device authenticated acceptance.
- Application rollback target: `5743a9406952875fe486fa233f76d13336a6a719`. No schema, inventory, account, payout or permission mutations are included.

## Grail spotlight and unified Naruto — 2 October 2026

The requested follow-up replaces the generated card-back hero with the exact English Umbreon VMAX 215/203, Monkey.D.Luffy OP05-119_p2 manga and Son Goku FB01-139_p2 super alternate artwork. Original image bytes and official SAMPLE marks are preserved. Source URLs, catalogue keys and SHA-256 hashes are in `backend/app/static/grail-art/sources.json`. The authenticated spotlight is labelled reference artwork, with no inventory, price, ownership or storefront-rights claims. Clicking a card resolves its exact server catalogue key and opens the existing product detail sheet; unavailable or changed references show an explicit message. Navigation or a newer search cancels stale detail results.

The hero headline is now “Find your next grail.” System sans-serif typography replaces Impact in the home and shared sign-in; spacing and card layout adapt to desktop, tablet and phone widths. The approved logo and scanner remain untouched.

`NARUTO` is a browse alias spanning `NARUTO_KAYOU` and `NARUTO_BANDAI_LEGACY`. Games aggregate counts and distinct languages; sets and products expand the alias through parameterized arrays. Set selection passes the original system, provider, language and set ID, preserving exact identities even when providers reuse a set ID. No database records are merged or renamed. A read-only production check found 43 Kayou and 38 Bandai Legacy released sets.

Validation: 2,396 backend tests and all dashboard suites pass, including 13 catalogue scenarios. New regressions cover aggregate counts, explicit-system compatibility, set identity boundaries, exact spotlight resolution, missing references and navigation away during loading. Browser fixtures cover both roles at 1440, 1024, 768, 390 and 320px with loaded artwork, no horizontal overflow, working spotlight links and a single Naruto tile. Authentication and fixture product responses are mocked; no production inventory writes. Application rollback target for this follow-up: `9883e06c873c6bed5be1e9b568680cf49eec8ccd`.
