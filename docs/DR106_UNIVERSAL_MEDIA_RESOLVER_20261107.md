# DR106 — Drop Rate universal media resolution (Phase 1)

**7 November 2026 · production-safe release candidate**

## 1. What we're building

A channel-agnostic, deterministic `resolve_media(item, assets, channel, purpose)` service in `backend/app/media_resolver.py` for **DROP_RATE, SHOPIFY, EBAY, WHATNOT**. PostgreSQL continues to own inventory, ownership, rights and media approval metadata. R2 retains byte storage. FastAPI makes listing-image decisions; n8n must not reimplement them.

This is a **shared decision layer and seller preview**, not a new uploader, image licence, scraper, automatic publication service or Whatnot connector.

## 2. Why

Previously Shopify selection was performed in `resolve_storefront_media`, eBay independently selected physical photos in `ebay_sales`, and Drop Rate's own inventory interface had no per-channel readiness preview. Different engines could drift, accidentally choose the wrong physical card's image, or mislead sellers into thinking the same photo was publishable everywhere.

## 3. Architecture and connections

```
Canon CARD + physical INVENTORY ITEM (owner and Inventory ID)
  -> tcg.media_assets (scope, exact printing/variant/language,
     photo of exact copy, rights, approval, source state)
  -> FastAPI resolve_media(channel, purpose)
     -> DROP_RATE: authenticated own-item preview
     -> SHOPIFY: listing decision, official-first where allowed
     -> EBAY: actual-item front + back photographs for the existing UK used-card flow
     -> WHATNOT: future adapter only; never publish before connection/review
  -> channel publication remains in its existing explicit, audited flow
```

- **Shopify:** Existing production `_launch_completeness` and read-only readiness now use the universal `SHOPIFY` decision. For low-risk raw cards, choose the *correct approved* official printing even if a scan photo exists. Preserve the scan for owner/evidence; certified slabs/high-value still require physical-item photos under the current policy.
- **eBay:** The existing owner-scoped first-party FRONT/BACK SQL still applies. The universal `EBAY` decision independently rechecks the owner, physical Inventory ID, source_type, rights status, approval, revocation, photo context for graded slabs, readiness and validated Shopify-hosted HTTPS image URLs. eBay may not silently use a generic official card scan as a listing photo. The existing inventory publish, idempotency, audit, price and seller prerequisites remain unchanged.
- **Drop Rate UI:** `GET /api/v1/media/resolve/{inventory_id}` is a **read-only authenticated owner-scoped** route returning all four channel decisions. Seller Hub's physical-item detail displays the channel image selection and does not create a listing or promote provider artwork. Its asynchronous read is guarded against account changes, closed dialogs and stale inventory selection.
- **Whatnot:** The single resolver exposes a `WHATNOT` decision but always reports `WHATNOT_CHANNEL_NOT_CONNECTED`, `publishReady=false`, and no transferable image URLs. Adding a real Whatnot adapter requires platform permission/account connection and independent integration tests.

**Decision contracts:** `channel`, `purpose`, `complete`, `publishReady`, `channelConnected`, `blockers`, `resolutionSource`, `selectedMedia`, `shopifyFileIds` and `imageUrls`. These represent **image readiness**, not all listing prerequisites.

No owner IDs may be supplied by the client. SQL is authenticated and owner-scoped. Asset selection is additionally checked by immutable physical ID / canonical ID, rights, approved state and requested channel. No public media endpoint, arbitrary third-party URL relay, stored payment data or automatic source licence claim is introduced.

## 4. Failure points

1. Wrong owner/inventory → 404 from owner scope; foreign physical image explicitly rejected in deterministic resolution.
2. Language/variant mismatch, inactive/revoked source, missing approval or permission evidence → not selected as official art.
3. eBay missing FRONT/BACK, pending/foreign/raw-not-slab or non-HTTPS approved physical image → fail closed without image URLs.
4. Unsupported marketplace or media purpose → reject (ValueError); unconnected Whatnot → no publish.
5. Stale owner session/selected inventory ID → stale UI results dropped.
6. Any UI/API failure → normal listing checks continue; never auto-publish, change balances, overwrite images or invent an official picture.

## 5. Tests and deployment

- Unit: `tests/test_universal_media_resolver.py` covers four channel outputs, owner isolation, wrong rights, variant/language, wrong slab context, unsupported channel, no Whatnot publication, no mutation.
- API: `tests/test_media_api.py` validates owner query bindings, read-only decisions and UI stale-session safety.
- Existing: `tests/test_ebay_photo_eligibility.py` tests the real SQL photo-filter contract, `tests/test_media_resolver.py` retains established Shopify priority and physical-evidence rules, `tests/test_shopify_readiness.py` checks shared resolver integration.
- Required gates: full backend/Python tests; dashboard JS; n8n image; eBay photo SQL regression and read-only API; GitHub review; Railway build/deploy and health readiness.

**Operational verification after deploy:** signed-in owner opens a real item, confirms media choices in Drop Rate channel panel, cross-checks exact card and physical copy (and no foreign owner photos), then runs existing Shopify/eBay *preview* flows without publishing. No image writes or catalogue migrations in this change.

## 6. Deliberately separate follow-up releases

- Attach **all** scan photos reliably to the correct physical Inventory ID; support front/back for graded copies and durable R2 original-byte integrity receipts.
- PSA/BGS/ACE/CGC cert source images: verify exact cert and publisher use before making them listing media; do not replace cert images or remove `SAMPLE` marks.
- Build rights-reviewed, exact-print official-art ingestion and approval for new YGO, Lorcana, MTG and Riftbound catalogues; require 25-print visual pilot and byte verification.
- Add actual Whatnot API/channel adapter only when its integration and media requirements are known and authorised.
