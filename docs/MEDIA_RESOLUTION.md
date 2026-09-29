# Existing-image-first media resolution

Drop Rate uses deterministic media rules before any image can participate in a Shopify listing.

## Goals

- Reuse legitimate, rights-approved canonical card imagery where permitted.
- Avoid unnecessary photography for ordinary low-risk raw cards.
- Keep exact physical-item evidence mandatory where condition/value/grade makes it material.
- Fail closed when identity, language, variant, source health or rights are uncertain.
- Preserve a full audit trail. Media records are revoked or marked dead rather than silently deleted.

## Rights tiers

`STOREFRONT_ALLOWED`
: Canonical card media with documented permission for storefront use. This is the only reusable third-party tier eligible for Shopify.

`MARKETPLACE_NATIVE_ONLY`
: May be used only on the originating marketplace. It can never be synced to Shopify.

`INTERNAL_REFERENCE_ONLY`
: Internal identity/reference use only. It can never be synced to Shopify.

`FIRST_PARTY_CAPTURE`
: A founder/consignor photo tied to one exact Inventory ID. Eligible for Shopify when approved and source-active.

Public availability is not evidence of permission.

## Resolver order

For a physical inventory item the resolver:

1. Looks for approved, source-active `FIRST_PARTY_CAPTURE` media tied to that exact Inventory ID.
2. If physical evidence is mandatory, requires exact front and back first-party photos.
3. Otherwise looks for approved `STOREFRONT_ALLOWED` canonical media matching:
   - catalogue/card identity,
   - language,
   - variant/art,
   - verified rights evidence,
   - active source state,
   - Shopify-ready media file state.
4. If no eligible media exists, the item remains blocked with an Action Required reason.

Marketplace-native and internal-reference media are rejected again at the Shopify media-sync boundary.

## Physical-photo policy

Default high-value threshold: £50.00 (`5000` minor units).

Override with:

`TCG_MEDIA_PHYSICAL_PHOTO_THRESHOLD_MINOR`

Physical front/back evidence remains mandatory for:

- graded cards,
- cards at or above the configured value threshold,
- raw cards whose condition is not Near Mint,
- reshoot/review/rejected-condition exceptions,
- identity exceptions.

AI is not part of this decision.

## Condition review

Low-risk raw Near Mint cards do not need photo-backed Near Mint verification solely to publish. Their stored human condition remains authoritative.

When physical-photo policy applies, the existing human review remains mandatory:

- raw: `VERIFIED_NEAR_MINT`
- graded: `VERIFIED_GRADED`

## Source governance

Media records track provider, provider asset ID, permission evidence, declared language/variant, rights tier, source status, source-check timestamp and revocation metadata.

Source states:

- `ACTIVE`
- `DEAD`
- `REVOKED`

A revoked source cannot be reactivated through the source-health endpoint.

Do not automatically probe arbitrary user-supplied URLs from the core backend. Source-health automation should be implemented inside trusted provider adapters to avoid SSRF and provider-terms issues.

## Admin/API controls

- create media asset: `POST /api/v1/shopify/media-assets`
- approve media rights: `POST /api/v1/shopify/media-assets/{asset_id}/approve`
- set source health: `POST /api/v1/shopify/media-assets/{asset_id}/source-status`
- revoke media rights/source: `POST /api/v1/shopify/media-assets/{asset_id}/revoke`
- Shopify media sync: `POST /api/v1/shopify/media-assets/{asset_id}/sync`
- local readiness: `GET /api/v1/shopify/readiness`
- per-item preview: `GET /api/v1/shopify/product-preview/{inventory_id}`

Existing `tcg.media_assets` audit triggers record create/update state changes.

## Source ingestion

Do not add a source adapter to production until its current terms/licence are verified. A source adapter must map its data into the media registry; it must not bypass resolver rules.

Examples of information the adapter must provide:

- canonical Card ID,
- source/provider,
- provider asset ID,
- image URL,
- exact language,
- exact variant/art,
- rights tier,
- permission evidence URL/note,
- source check/fetch timestamp.

## Failure handling

- Wrong language -> reject.
- Wrong variant/art -> reject.
- Unclear/no storefront rights -> reject.
- Dead/revoked source -> reject.
- Duplicate live media -> database/API conflict.
- Missing physical media where policy requires it -> Action Required.
- Shopify file not ready -> blocked until ready.
- Provider or Shopify failure -> retry is explicit; publication remains blocked.

## Testing

Coverage includes:

- rights tier selection,
- language/variant mismatch,
- dead/revoked source,
- high-value/graded physical requirements,
- low-value canonical reuse,
- first-party priority,
- non-storefront rights blocked at Shopify boundary,
- source-status/revocation controls,
- migration layout and source-governance fields,
- existing full project suite.


## Sealed product physical capture

Sealed/collection inventory uses the same founder media intake surface as cards, but follows
a different deterministic policy.

For `product_type in ('SEALED','COLLECTION')`:

- the media intake queue includes DRAFT/INSPECTION/APPROVED `FOR_SALE` inventory;
- exact physical packaging photography is required;
- only the **FRONT** side is required by default;
- the capture context is fixed to `SEALED_PRODUCT`;
- physical media must be `INVENTORY_ITEM` scope with `FIRST_PARTY_CAPTURE` rights;
- raw-card condition review is not reused for sealed products;
- the Shopify publication gate still independently requires identity confirmation,
  seal status, price, registered location and approved/ready storefront media.

The queue is only a work-list. Appearing in it does not approve identity, change inventory
status, publish a Shopify product or bypass rights checks.

Capture completion is context-aware. A FRONT image captured as a raw card or graded slab
does **not** satisfy a sealed-product requirement; only a valid `SEALED_PRODUCT` capture
does. Likewise, graded requirements accept only `GRADED_SLAB`, while raw-card requirements
accept only `RAW_UNSLEEVED`, `PENNY_SLEEVE` or `TOP_LOADER`. This prevents a valid
first-party image from being reused under the wrong physical-media workflow.

A previous route-level SQL filter admitted only `CARD` products even though the media
resolver and upload endpoint already supported sealed inventory. That filter is now aligned
with the existing resolver contract by allowing `CARD`, `SEALED` and `COLLECTION`.
