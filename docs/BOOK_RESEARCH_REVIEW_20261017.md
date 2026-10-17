# Beginner comic and manga identification

The 17 October 18:46 iPhone recording shows working book capture/OCR followed by
a long form requiring the collector to identify the printing, edition and cover.
The requested outcome is research inside the app, automatic suggested details,
and publisher artwork the collector can compare with their own book.

## Behaviour

- Existing cover OCR stays separate from publisher research. A bounded Responses
  API request uses the existing configured recognition model/account, web search
  restricted to publisher domains, at most three search-tool calls, four candidate
  editions and a 40-second research deadline. No new service, provider account,
  paid subscription, scraper or background job is introduced. Normal existing
  OpenAI usage, including search-tool usage, applies.
- Only actually consulted publisher issue/volume URLs are admitted. Conflicting
  observed issue, language, barcode, year, printing, category and edition are
  rejected. Unknown printing is retained as unknown; an ISBN is not proof of a
  first printing. Research failure preserves the original OCR and manual recovery.
- One visually suggested cover can prefill the form. Multiple candidates remain
  visual choices. None is automatic identity, grade, condition, price or stock
  approval. The collector explicitly saves a draft personal-collection item.
- The main review starts with publisher cover choices and clickable source links.
  Book metadata is collapsible. Additional barcode/copyright-page photos remain
  available and unconfirmed optional details do not prevent collection intake.
- Publisher artwork is restricted to the existing Marvel/DC/VIZ CDN validators,
  authenticated receipt-bound thumbnail delivery, bounded decoding and no browser
  credentials sent to publishers. Other supported publisher searches can supply
  metadata and links while unsupported artwork remains unavailable.
- An explicitly selected cover follows the saved physical copy through an
  idempotent owner-bound `book-reference:<inventory_id>` recognition receipt. The
  current book identity/language must still match its stored digest. No catalogue
  verification, media approval, Shopify listing, market-price or financial state
  is changed. Intake retry reuses the original copy if artwork journalling fails.
- Existing scan cap/deduplication remains; original photos are not stored in
  recognition journals. Search instructions forbid private text/certificate queries.

## Validation and release

Local full Python suite: 6,124 passing before final release checks; scanner suite:
50 interactions passing. Added source/identity/SSRF/ambiguity tests, signed HTTP
and real PostgreSQL owner-isolation/intake/cover-receipt scenarios, and Chromium +
WebKit phone/desktop cover-choice tests in the existing collection workflow.
All six PR #678 workflows passed. CI screenshots were inspected at phone and
desktop sizes, including valid decoded artwork, contained cover buttons and
collapsed additional-photo controls. The first browser runner had a screenshot
protocol failure in an existing card scenario; the failed job passed on rerun.

`backend/scripts/book_research_smoketest.py` is an explicitly invoked one-request
probe using a public VIZ cover and the deployed OpenAI configuration. It performs
no database operations and must not become a recurring startup task. For this
release append it to the existing Railway pre-deploy check, inspect its receipt,
and restore the prior pre-deploy command afterwards. A failed probe blocks the
candidate while the prior live deployment remains available. This validates the
API/search/source/artwork contract, not real physical-book recognition accuracy.

API reference checked: https://developers.openai.com/api/docs/guides/tools-web-search
and https://developers.openai.com/api/reference/resources/responses/methods/create .

Actual provider: the configured gpt-6.1-sol returned VIZ product 139, ISBN
9781569319017, its exact publisher cover and a positive visual match. The initial
probe was a false negative because VIZ returned the same print record at the
verified `/paperback` URL. The probe now accepts only that specific format alias,
requires the exact ISBN and image plus a positive visual match, and rejects digital
URLs, other products, changed ISBNs and mismatched artwork. Seven regression cases
cover the gate. No production database or account operation is performed by it.

Deployment, temporary pre-deploy restoration and live asset readback receipts are
maintained in [PR #678](https://github.com/pulltheorytcg/drop-rate-backend/pull/678).
Rollback is the prior successful API deployment; no schema migration or production
data rewrite is required. User-owned books still need a fresh real-device scan
after release to evaluate recognition on their photographs.
