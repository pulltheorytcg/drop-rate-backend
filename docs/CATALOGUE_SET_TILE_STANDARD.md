# Drop Rate Seller Hub — catalogue set tile standard

**Scope:** Search → Sets, shared by Founder HQ and Seller Hub. This is a focused fix to the current navigation surface, not a new artwork provider, product-media approval path, database schema or Shopify storefront change.

## Why this change is required

A reported screenshot on 10 October 2026 showed a Pokémon set grid combining clean expansion logos, dark game-mark tiles and an unrelated Bulbasaur **card preview** under *Crimson Blaze*. The old `catalogue-browser.js` intentionally used a set's first reference card image when no exact set logo was known, and rendered that fallback at a different height. It also hid the set name if a logo loaded, causing inconsistent card identity and visual hierarchy. The `SETS_SQL` query paid for that unwanted preview join.

## Visual contract (single reusable set tile)

1. A constant **128px artwork frame** with a subtle neutral/game-tinted background, centered contents, safe padding and `object-fit: contain`. No stretching, clipping, publisher-mark removal, ad badges or generated counterfeit logos.
2. The artwork can be only (in precedence order) the **exact game + language + set** logo from existing `DropRateTitleArt.set`; the official game mark from `DropRateTitleArt.game`; or the built-in navy/gold brand placeholder glyph. The markup never invokes `productImage` for a set.
3. Every tile, regardless of artwork outcome, shows a consistent metadata stack: **game**, **set name** (two-line maximum), **set code**, and below it **owned/checklist progress** and **known owned value**. The release-date badge is always in the same corner if the date exists. Unknown values remain pending.
4. One bordered light-surface card treatment with subtle hover feedback, consistent grid sizing and label spacing. Very gentle game color tints distinguish franchises; no full-bleed dark cards mixed with loose logos. Respect `prefers-reduced-motion`.
5. Load failure or missing logo removes the broken image and reveals the same branded placeholder; it must **never** trigger an arbitrary card, sealed-product or other-set preview. Product-detail card photos and the original approved Shopify media remain unchanged.
6. Existing exact title-art sources in `backend/app/static/title-art/sources.json` and the checked-in TCGdex logo lookup remain the authority. Do not promote recognition/reference card art to set art. Missing exact logos are tracked as a coverage problem; we do not invent publisher assets.

## API boundary

`/api/v1/catalogue-browser/sets` now returns set metadata only. It no longer joins reference-card/pack image URLs into set rows; response guards remove legacy `image_url`, `source_kind`, `provider_id` and reference-image-path fields. `/products` retains exact printing artwork and thumbnail fallback behaviour. The source of truth for ownership, values, set identifiers, language and release dates is unchanged.

## Failure scenarios and tests

- Exact official logo → image loads in the standard frame while all labels remain visible.
- Unmapped set such as `Crimson Blaze` → game logo/standard branded fallback, **not Bulbasaur**.
- Official/game logo load failure → local placeholder remains and no second external image request is attempted.
- No artwork, long set names, missing date → same fixed frame and clamped title.
- English/Japanese variants → lookup remains exact-language; no cross-language substitution.
- Mobile two-column and desktop six-column grids use the same tile component.
- JSDOM test asserts identical card structure, no preview DOM or URLs, exact logo resolution and failed-image fallback. Pytest asserts that set SQL and API never supply a first-card image.
- Verify production response and a real signed-in mobile/desktop visual pass **after CI and deployment**. Those real-device checks are not claimed by the automated fixture suite.

## Rollout and rollback

Modify only `backend/app/static/catalogue-browser.js`, `catalogue-browser.css`, `backend/app/catalogue_browser.py`, associated tests and this document. No migrations, provider requests, new services, owner changes, prices, recognition expansion, marketing workflows or Shopify theme publishing.

Deploy with ordinary reviewed GitHub PR and existing Railway auto-build/pre-deploy gates. Roll back to previous `main` commit if unexpected navigation regressions appear; never alter physical inventory or Shopify publication to roll back this UI change.

**Acceptance:** The same normalized artwork frame and set metadata are used for every set; no set ever displays a card preview as its cover; missing art fails safely; set navigation and owned/value filters remain intact.
