# Seller Hub — CSV and TSV Collection Imports

**Status:** first seller-facing, owner-only collection upload release. Builds on the existing reviewed Founder Dashboard import system, not a parallel database or AI uploader.

## What

From **Seller Hub → Inventory → Import**, choose **Collectr**, **Holodex**, or **Other**. Select a CSV or TSV export (UTF-8, max 8 MB and 5,000 source rows per batch). Use optional default game/language and source-column mappings for exports with unfamiliar headings. Press **Preview collection** to inspect ready, review and skipped quantities. Only a separate, deliberate **Import Draft copies** action creates physical items.

The Founder Dashboard already supported this flow; it was absent from Seller Hub because `inventory-imports.js` was loaded only in the founder dashboard and `/api/v1/imports` routes were platform-admin-only. The new seller interface provides its own responsive modal and only approved subset of the same deterministic import pipeline.

## Connections

- `backend/app/owner_imports.py` offers `/api/v1/owner/imports` endpoints for signed-in OWNER portal accounts only: POST preview, GET batches and details, POST commit, POST candidate resolve/skip, GET search existing canonical catalogue. All mutations reuse `imports.py` / `import_review.py` without relaxing their original founder-admin protections. No bulk enrichment, identity override, store publication or catalogue-write route is made seller-accessible.
- `ownership.current_owner` resolves exactly one active owner membership from the user-scoped PostgreSQL transaction. Every import batch, candidate and physical copy is explicitly selected/inserted with that owner ID, never one supplied in uploaded CSV. Founders and consignors cannot silently move another owner's inventory.
- Collectr exports use existing snapshot-delta reconciliation: new physical copies only for increased quantities, unchanged quantities skipped, decreases or disappeared cards require review. A seller's deliberately skipped new item is excluded from subsequent snapshot baseline; this prevents a false "already imported" record.
- Collectr unmatched canonical identities are **REVIEW** for restricted sellers. Seller can select an existing canonical match, or skip; a shared new canonical card may only be created from the original authorised founder flow. The committed physical items always start as individually owned, unverified `DRAFT`, not Shopify-published stock.
- HoloDex is a mapped **CSV import** option, not an unverified remote API integration. Its export format can vary, so the optional column mapping and review are important; unsupported identity rows are never silently guessed. Other supports UTF-8 CSV and tab-delimited TSV, including a UTF-8 BOM.
- File fingerprint (per owner) prevents previewing/committing the identical uploaded file twice. A versioned PREVIEW batch allows review/skip changes, supports resuming previous batches and blocks duplicate commit. Non-Collectr exports are not collection snapshots and may contain genuinely separate additional physical copies; the UI asks for review before an explicit commit.

## Potential failure points

1. Unknown canonical identity / ambiguous set / missing language / invalid grade or condition: REVIEW, no auto-creation of seller canonical cards. If unresolved, deliberately skip the affected candidate or let Drop Rate investigate.
2. Malformed CSV, wrong file extension, file over 8 MB, more than 5,000 rows, bad quantity, non-GBP acquisition cost, incorrect column mapping: reject with a visible message.
3. Same Collectr snapshot/re-upload, concurrent newer baseline, duplicate logical identity rows, updated quantities, manually skipped source rows: fail closed or reconcile new copies only.
4. Owner changed, multiple memberships, wrong role, attacker-supplied owner columns, request replay: reject via active membership and owner-constrained SQL. A seller never obtains `/api/v1/imports` founder privileges.
5. A successful import creates only physical DRAFT copies; any listing needs future explicit identity, condition/grade, price and image checks through normal intake.

## Tests / release gates

- Python tests verify original admin import protection, owner-only endpoint allowlist, CSV+TSV support, safe column mapping, Collectr restricted unknown cards, founder Collectr compatibility, baseline skip semantics, and no forbidden canonical creation on seller commit.
- UI tests verify Inventory dropdown choices, preview counts, column mapping, catalogue matching, deliberate skip, UTF-8 file checks, authenticated commit and owner inventory refresh; XSS and private data must remain text-only.
- Existing dashboard, backend, real PostgreSQL and pinned n8n checks must all pass before merge. Verify Railway app healthy and inspect signed-in Seller Hub before claiming full live acceptance; no production consignor data import is simulated or triggered.
- No Supabase migration, Shopify product/order update, payout mutation, n8n workflow, marketing automation or new provider connection.

## Important current limitations

CSV and TSV supported; **Excel XLSX, PDFs, screenshots and direct Collectr/HoloDex account sync are not implemented**. For an unsupported export format, convert to CSV first; do not claim a nonexistent parser. Mapped columns must be selected before creating the first preview; remapping an already fingerprinted preview requires an explicit reviewed reset workflow (not implemented). Prices from external exports are recorded only as source acquisition costs when valid GBP, never accepted as definitive automated market values.

This release remains subordinate to the storefront/fulfilment launch freeze except for the user-requested Seller Hub import capability. It does not activate new catalogue providers or sell channels.
