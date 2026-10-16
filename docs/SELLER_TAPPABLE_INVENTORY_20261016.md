# Seller Hub — tap anywhere to view item details (16 October 2026)

## 1. What changes, and why

The founder's iPhone screenshot showed two tightly packed inventory columns with huge **"Last known DD/MM/YYYY"** dates and a redundant yellow **Manage** button under each card. The founder asked that the entire card open details. This release changes only the owner-scoped inventory *grid* presentation: title, original artwork, quantity, status, market value and Store Price remain scannable; the item card itself becomes one 44px+ accessible button covering the entire tile.

- No **Manage** button in the grid. An absolutely positioned, transparent native **View details for [card name]** button covers the whole card. Clicking/tapping any visible card whitespace, image or price opens the *existing* owner detail modal. Keyboard Enter/Space activates it naturally.
- An independent 44×44px reference-price refresh button, if permitted, remains accessible at the lower right of artwork. It sits above the card button and does **not** open the detail view or duplicate a price action. Existing owner-scoped API/auth/retry remain untouched.
- The GBP market price is still displayed. If the source is an older **last-known** price, the grid removes the long original timestamp and uses an unobtrusive **Historical reference** caption instead. This is not represented as current market evidence. Its **full price and last checked date remain in the detail view** with the full pricing provenance, alongside condition, inventory ID, copy controls and listing channels.
- True current or official guide values retain their previous labels. A truly unpriced item continues to show "Value pending" rather than £0 or a copied listing price.
- Keep existing display grouping by exact canonical identity, owner and grade/condition; no physical stock rows are merged or mutated.
- CSS/JS cache versions are bumped so mobile Safari loads the actual update.

## 2. Connections

Existing shared owner inventory grid (`owner-portal.js`), strict original currency/price evidence formatter (`reference-value-display.js`), tile CSS (`owner-inventory.css`) and owner-scoped details UI (`owner-inventory.js`). Routes, checkout, permissions, returns, history, payouts, pricing engine, market adapters and database schemas are unchanged.

## 3. Failure points and testing

- Card click should trigger just one authenticated owner details request, never automatically update prices or publish a listing.
- The refresh button remains separately operable (mouse/keyboard/touch) and does not open the modal.
- Historical values must remain tagged as older on grid; the *date itself* stays available inside the detail view.
- Quantity status and multi-owner identity grouping must remain intact. Buttons and artwork must not overflow at 320/390/430/1440px.
- Regressions in `tests/ui/owner-inventory.cjs` and `tests/ui/owner-inventory-browser.cjs` cover accessibility, click and keyboard activation, dates and refresh isolation across Chromium and WebKit. Existing complete backend, real PostgreSQL and seller ownership tests must pass.

## 4. Market history retention/capacity decision

The founder also agreed to keep useful recent market history in the live database **where storage permits**, while archiving older evidence in private Google Drive. Production currently has **50,378 unarchived history rows occupying about 77 MB** — these are all from **15 October 2026**, meaning an unconditional 30-day live retention rule would retain almost everything and **cannot free the current 405.5 MB database below the 400MB price-refresh gate**.

The **current market source-price caches remain live in Supabase** when immutable raw history is archived. They are not history rows and must never be purged by the archiver. The existing verified archival helper operates on the whole history table (full-content integrity lock and transactional TRUNCATE); it does **not** support safe partial deletion and should not be misrepresented as such. Historical price charts cannot dynamically read older data from Drive yet.

Therefore this release **does not silently add a 30-day table-row retention policy or delete history**, which would either fail to reclaim storage or require unapproved database/restore design work. The safe near-term route is fully verified cold archival of the **entire history**, preserving current live quotes and latest values. A future compressed recent history / read-through archive solution must be designed, tested in disposable PostgreSQL and explicitly reviewed before altering the helper. No history rows, pricing caches, ownership or financial data are changed here. See existing `docs/REFERENCE_HISTORY_ARCHIVE_RUNBOOK.md`.

This distinction is important: **the requested inventory UI fix can deploy safely now**, but the 30-day historical trend retention feature is not claimed as complete until the storage, integrity and chart-reading design is validated.
