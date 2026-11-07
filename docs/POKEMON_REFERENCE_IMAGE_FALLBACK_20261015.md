# Pokémon reference-art unavailability — 15 October 2026

## Live source audit

Drop Rate's source-of-truth `tcg.reference_cards` contains **9,124 Japanese** and **1,780 English** TCGdex references without an image URL (10,904 missing actual photographs). The existing independent canonical media catalogue has **zero** approved, exact source-ID/name/set/language/number matches that can legally be substituted for this cohort. TCGdex's provider documentation explains that `image` is optional and absent when an image has not been submitted/processed; URL shape alone is not proof that an official scan exists. References remain fully searchable by identity and number, and their actual price status is independent of image availability.

**Do not fabricate files, append high.webp to absent URLs, reuse another printing or language's photo, strip a publisher watermark, or claim the image problem is globally solved.**

## What this UI release does

On mobile/desktop Seller Hub, when an exact TCGdex Pokémon reference has no image (or its exact low/high images both fail), show a **locally bundled Pokémon game mark** with text **Card image not yet available · Reference only**, rather than an empty broken image. It is explicitly a neutral branded fallback, not a rendering of that physical card. Real, verified image URLs still take precedence; source-image failures continue to show a visible error state and image fallback. Canonical-owner images and physical media approval are unchanged.

The assets are already bundled by Drop Rate. No new external source, paid integration, scraping, image upload, stock update, identifier inference, or reference database write. The image node remains absent for cards without a real image URL, and the fallback does not receive any physical-copy valuation authority.

## Connections, failure modes, tests

- UI: `backend/app/static/catalogue-browser.js` and `catalogue-browser.css` used by Founder HQ/Seller Hub. Versioned `owner.html` assets ensure mobile Safari loads it.
- Missing source art: fails closed into source-labelled fallback; distinct variant IDs or language cannot share another card image.
- Invalid exact URL: existing TCGdex low→high fallback remains; after both fail it shows the source-labelled fallback.
- No image-derived price or Shopify publication; existing source-canonical and physical stock histories remain untouched.
- Tests: initial zero-image state, two failed TCGdex URLs, explicit placeholder, no substituted card image, restored freshness of CSS/JS via versioned URLs; all existing browser, inventory and backend tests.

## The remaining source work

Actual source-image recovery still needs provider-supplied images or an appropriately licensed second asset source with **exact game/set/number/printing/language** proof, delivered through the existing authorisation and media-review process. The 10,904 original missing records remain missing until verified data is imported. Do not count this UI improvement as image coverage.
