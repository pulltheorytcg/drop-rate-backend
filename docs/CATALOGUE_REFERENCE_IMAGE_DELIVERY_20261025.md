# Catalogue reference artwork delivery — 25 October 2026

## Purpose and scope

Drop Rate indexes approximately 69,545 reference cards, and 59,181 currently have
an upstream `reference_cards.image_url`. A live app needs to display the exact
printing's image without creating an inventory item, assigning a value, changing
ownership, or approving imagery for Shopify.

This is an **on-demand display reliability change**, separate from the private
Cloudflare R2 media mirror. It does not imply that every upstream image is
licensed for re-hosting, and it does not upload those references to R2.

## Delivery choices

1. Only rights-approved canonical media in `media_assets` can be mirrored to
   private R2 through the existing `media_object_mirrors` process. Its live
   presigned URL remains the app's first choice when available.
2. Reference cards with an exact TCGdex/Pokémon, Bandai/Dragon Ball or official
   One Piece card URL receive an authenticated, database-identity-based
   `/catalogue-browser/reference-image` fallback. Pokémon and Dragon Ball
   attempt the provider URL first. One Piece's known cross-site-blocking image
   host continues to use its authenticated route first.
3. Naruto archive and marketplace listing images continue to be external
   references; they are **not** admitted to this app-side relay or private R2
   mirror, and no rights record is forged. Sealed-product and publisher book
   paths retain their previous behaviour.
4. Grid fallback returns a bounded WebP thumbnail with a private browser cache
   lifetime. Image requests are limited by the existing request queue and
   server-side fetch/conversion controls; external URL parameters are ignored.
5. If the provider URL, network or relay fails, the existing on-screen image
   fallback remains. Prices always come from live Supabase pricing tables,
   not image metadata or R2 objects.

## Observed starting source coverage

| Game | Records | With reference image URL |
| --- | ---: | ---: |
| Pokémon | 36,776 | 26,412 |
| One Piece | 9,007 | 9,007 |
| Dragon Ball Super Masters | 9,002 | 9,002 |
| Dragon Ball Fusion World | 7,594 | 7,594 |
| Naruto Bandai Legacy | 4,487 | 4,487 |
| Naruto Kayou | 2,679 | 2,679 |
| **Total** | **69,545** | **59,181** |

Of the missing Pokémon images, 9,124 are Japanese and 1,240 English. Existing
URLs are not proof that the remote image still loads. These counts must be
re-measured after deployment from actual browser successes and provider errors.

## Failure cases and safeguards

- Invalid/attacker-supplied URL: the route uses database-selected identity and
  tightly matched HTTPS source hosts only. A client cannot specify a remote URL.
- Hostile redirects, oversize or malformed images, HTML: rejected by
  `recognition_images.reference_image_bytes` and `catalogue_artwork` limits.
- Cross-site provider blocking, missing remote art or rate limits: fall back
  to another known source or a clear unavailable state; do not fabricate art.
- Expired private R2 signature or R2 outage: reference source fallback remains.
- High Railway bandwidth: proxy only on direct-source failure except known One
  Piece blocking; use bounded grid previews and browser caching.
- Ownership, pricing, listing, rights: untouched by this UI transport change.

## Verification and activation

1. Unit tests for exact provider/game/host allowlist, user access and forbidden
   arbitrary client URLs.
2. UI tests for direct-provider-first, One Piece proxy-first, R2 fallback,
   thumbnail sizing and bounded concurrent image requests.
3. Probe representative public TCGdex/DBZ source images with HTTP HEAD.
4. Deploy through normal GitHub/Railway release checks; confirm live API 200,
   then inspect signed-in Seller Hub cards for Pokémon, One Piece and both
   Dragon Ball games across grid and detail on desktop and mobile.
5. Continue separate effort to source the ~10,364 genuinely missing Pokémon
   artwork references, investigate Naruto archive licensing and validate a
   published n8n error path before recurring R2 mirroring is enabled.

## Rights note

Public visibility is not blanket redistribution permission. Even though
reference image URLs already exist in the catalogue, new permanent copies in
R2 must be separately eligible for that use, and the provenance/right status
must not be misrepresented. Publisher permissions/terms or other lawful grounds
should be assessed before any mass ingest. A future takedown workflow must
stop delivery if an approved source is revoked.
