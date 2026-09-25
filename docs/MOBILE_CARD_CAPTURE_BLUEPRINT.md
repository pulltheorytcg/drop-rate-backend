# Mobile Card Capture and Direct Listing Blueprint

## Status

Deferred product feature for the AI identification phase. The first client is expected to be an iOS app, but the workflow must use the same authenticated FastAPI APIs and deterministic Shopify publication gate as the founder dashboard.

## Product outcome

A founder or approved operator can photograph a physical card with a phone, review a database match, correct it when necessary, complete the physical inventory record and request publication to Shopify without re-entering the card in a separate system.

The phone app is a capture and review client. It is not a second source of truth and it cannot publish directly to Shopify.

## Core workflow

1. The operator starts a capture session and photographs the front of the card. The back is requested whenever the media policy or risk rules require it.
2. The app uploads the images through authenticated, short-lived upload URLs.
3. The backend creates identification candidates using visible card facts such as game, name, set symbol, card number, language, variant and rarity.
4. The app shows the best candidate and confidence, plus alternative matches where ambiguity remains.
5. The operator confirms the match or chooses **Find another card**.
6. Manual recovery starts with card number search, then narrows by game, set, name, language, variant and rarity. Card number alone is never treated as unique.
7. The selected canonical card is attached to a new physical Inventory ID. Owner, acquisition cost, condition or grade, language, storage location and Store Price are completed or explicitly sent to Action Required.
8. The backend checks identity confirmation, ownership, duplicates, media rights/readiness, pricing and the Shopify product-completeness rules.
9. A publish request creates or updates a Shopify draft using the Inventory ID as the deterministic SKU. The backend verifies the remote product, quantity, weight, media and collections before activating it.
10. Any failed or uncertain step remains recoverable in Action Required. Retrying the same capture or publish request must not create duplicate inventory or Shopify products.

## Matching rules

- AI returns candidates and confidence; it does not silently create a canonical card identity.
- High-confidence matching still requires an explicit operator confirmation for the first version.
- Low-confidence, high-value, unusual-language and suspected-counterfeit cards require human review.
- The canonical match key should combine game, set, card number, variant and language where available.
- Manual search must expose the distinguishing fields needed to separate cards that share a number or name.
- A manual correction is recorded as an audit event and retained as training/evaluation feedback, but it never rewrites the canonical catalogue silently.

## Publication boundary

The iOS app calls the backend only:

```text
Phone camera
  -> capture session
  -> image upload
  -> identification candidates
  -> operator confirmation or manual card-number search
  -> physical inventory draft
  -> completeness and risk checks
  -> Shopify draft
  -> remote verification
  -> Shopify active product
```

Shopify credentials remain server-side. Supabase/PostgreSQL remains authoritative for the canonical card, physical Inventory ID, owner, cost, condition, language, price, status and Shopify linkage.

## Future data model

The implementation should add owner-scoped records for:

- capture sessions and idempotency keys;
- original and processed capture images;
- identification candidates, model/version and confidence;
- operator confirmation or manual-selection events;
- links from a completed capture to the resulting physical Inventory ID;
- publication attempts and failure reasons.

Images should use private storage during review. Only approved, rights-verified media may be attached to a Shopify product.

## Security and failure controls

- Supabase authentication and role checks apply to every session.
- The mobile client never receives service-role, Shopify Admin or other server secrets.
- Upload type, size and count are restricted; malware/content checks occur server-side.
- Duplicate detection checks image hash, capture idempotency key, certificate number for graded cards and existing physical Inventory IDs.
- Offline or interrupted uploads resume safely.
- A failed Shopify response leaves the product as a recoverable draft and records an exception.
- Ownership cannot be inferred from the signed-in device; the backend validates the selected owner against membership and permissions.
- Every identity correction, owner assignment, price change and publish action is audited.

## Delivery sequence

1. **Backend contract first:** capture-session, candidate-search, manual-selection and inventory-draft APIs.
2. **Responsive workflow prototype:** prove the scan/review/manual-search journey against real cards before committing to native UI details.
3. **iOS application:** camera capture, crop/quality guidance, upload queue, candidate review and Action Required.
4. **Controlled Shopify publish:** enable only for complete, low-risk inventory and verify one item at a time.
5. **Scale and learning:** batch capture, better candidate ranking and measured model improvement from confirmed corrections.

## Acceptance criteria

- A correct scan can become a confirmed physical Inventory ID without duplicate data entry.
- An incorrect scan can be recovered by card-number search and explicit option selection.
- Two cards sharing a number cannot be conflated without the operator seeing the distinguishing set/game/language/variant fields.
- Incomplete or uncertain records cannot become active Shopify products.
- Repeating the same request does not create a second inventory item or Shopify product.
- The complete history from image capture to published SKU is auditable.
