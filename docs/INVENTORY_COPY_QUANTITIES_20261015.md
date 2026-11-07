# Unified inventory quantities — 15 October 2026

Matching raw cards now appear as one entry with a quantity in Seller Hub and Founder HQ, in both grid and table views. The same rule covers matching sealed products. A new copy joins its existing entry after inventory reload.

Grouping requires the same owner, canonical printing, language, condition and seal state. Unknown condition remains distinct from a stated condition. Every graded or certificate-bearing copy stays individual, including incomplete grading records. Sold and withdrawn history stays separate from active inventory. Different approval statuses, sale intents, costs and asking prices do not create duplicate active tiles: the entry shows mixed status and price ranges where necessary, and management still selects an exact physical copy.

The database pages groups before loading their members. A quantity therefore includes all copies matching the current filters, even when they would previously have straddled a 50-copy page. `group_copies=true` opts the web inventory endpoints into this contract: `total` counts entries, `copy_total` counts physical records, and `items` retains every original copy in the selected groups. Older callers keep per-copy pagination. The existing owner predicate, restricted connection and RLS remain in force.

The shared browser helper preserves the original copy objects and immediately displays available market evidence from the first inventory response. Grouped market values are labelled per copy; comparison/guide labels remain intact. Founder selection includes the actual individual IDs, and editing exposes a copy selector. Seller management uses the same SQL identity/state boundary as pagination. No physical rows are merged, deleted, re-owned, reconditioned, approved or repriced by display grouping. No schema, provider, service, subscription or Shopify publication changes.

## Production read-only baseline

The exact grouping expression was run against current production data before release:

- 614 physical copies → 557 display entries, across all owners independently.
- 43 groups with multiple copies; 57 repeated tiles removed; largest group 6 copies.
- The two unknown-condition Capone OP11-101 drafts form one quantity-2 entry. The explicitly Near Mint copy remains separate.
- Ownership, identity, workflow, condition, language, grading, certificate, seal, Store Price and identity-confirmation fingerprint: `cc0e9c744ce8fb918799ab981b1c847d`.

## Verification and release gates

- Full local backend suite passed (5,903 tests; existing Starlette deprecation warning).
- Complete JSDOM suite passed, including new founder price-column alignment, original-object bulk selection and exact-copy editor scenarios; seller mixed-status raw grouping, printing/language/condition/grading/certificate/history/owner separation and immediate comparison-price scenarios.
- Real PostgreSQL CI checks a 62-copy group across page boundaries, counts, filters, graded and certificate-only isolation, owner RLS and unchanged physical rows.
- Chromium and WebKit CI check raw quantity entries at 320, 390, 430 and 1440px, including visible prices and no horizontal overflow.
- Exact-head CI success, Railway terminal SUCCESS, live asset equality/readiness and unchanged production copy-state fingerprint remain release gates. The deployment receipt is recorded on the release PR.
