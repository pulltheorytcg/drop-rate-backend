# Expanded collectible source-batch receipts — 2 November 2026

**Status:** Read-only metadata previews, not production ingestion. These receipts
capture bounded validation runs so that expiring GitHub Actions artifacts are
not mistaken for long-term catalogue data.

| Source and window | Source rows examined | Validated candidate records | GitHub run |
| --- | ---: | ---: | --- |
| MTGJSON Magic Foundations (FDN), offset 50, limit 100 | 100 | 200 print/finish variants | [41371462498](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41371462498) |
| Rebrickable LEGO 2026 eligible sets, offset 50, limit 100 | 100 | 100 set models | [41371462498](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41371462498) |
| YGOPRODeck Yu-Gi-Oh TCG, offset 25, limit 50 | 50 | 117 printings | [41371462498](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41371462498) |
| MTGJSON Magic Foundations (FDN), offset 150, limit 100 | 100 | 200 print/finish variants | [41371836946](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41371836946) |
| Rebrickable LEGO 2026 eligible sets, offset 150, limit 100 | 100 | 100 set models | [41371836946](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41371836946) |
| YGOPRODeck Yu-Gi-Oh TCG, offset 75, limit 50 | 50 | 130 printings | [41371836946](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41371836946) |
| **Totals (candidate occurrences, before cross-run deduplication)** | **500** | **847** | |

## Validation and safety

- Both source-preview workflows concluded **success**. The CI validator asserted
  zero Supabase writes, R2 uploads, mirrored images, verified market values,
  and Shopify products in all six preview reports.
- The workflows have only `contents: read` GitHub permissions and do not
  receive production, R2 or Shopify credentials.
- The first batch's 7-day JSON report artifact is ID `13109546054`;
  the second batch's is `13110160160`, expiring 9 November 2026.
- Each run validates uniqueness within its own window. The **847 total is not
  a globally deduplicated SKU count**; repeat-card or variant identities
  across source windows must be reconciled before writing to any catalogue.
- The source reports exclude market-price and image claims. They are not
  licensed publication feeds, Shopify inventory, sales evidence or seller stock.
- Do not bypass the Rebrickable commercial reuse review, Funko/Topps/Panini
  authorized checklist requirement, image redistribution rights, or separate
  verified UK sold-price provenance rules.

## Release boundary

The migration `20261101205040_collectible_catalogue_expansion.sql` is still
unapplied. The canonical GitHub migration gate needs the project's separate
Postgres administrator password (not the GitHub/Supabase dashboard OAuth
session); the app's Railway `tcg_api` role cannot perform DDL. Production
database headroom is limited, so the bulk catalogue should remain R2-first,
with only bounded, indexed identities/materialized records in Supabase after
reviewed capacity tests.

No app deployment, production schema write, R2 feed activation, provider-image
copy or Shopify listing has been authorized by these preview results.
