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
| MTGJSON Magic Foundations (FDN), offset 250, limit 100 | 100 | 200 print/finish variants | [41447889682](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41447889682) |
| Rebrickable LEGO 2026 eligible sets, offset 250, limit 100 | 100 | 100 set models | [41447889682](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41447889682) |
| YGOPRODeck Yu-Gi-Oh TCG, offset 125, limit 50 | 50 | 119 printings | [41447889682](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41447889682) |
| MTGJSON Magic Foundations (FDN), offset 350, limit 100 | 100 | 120 print/finish variants | [41448062210](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41448062210) |
| Rebrickable LEGO 2026 eligible sets, offset 350, limit 100 | 100 | 100 set models | [41448062210](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41448062210) |
| YGOPRODeck Yu-Gi-Oh TCG, offset 175, limit 50 | 50 | 150 printings | [41448062210](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41448062210) |
| MTGJSON Magic Foundations (FDN), offset 450, limit 100 | 100 | 137 print/finish variants | [41449050457](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41449050457) |
| Rebrickable LEGO 2026 eligible sets, offset 450, limit 100 | 100 | 100 set models | [41449050457](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41449050457) |
| YGOPRODeck Yu-Gi-Oh TCG, offset 225, limit 50 | 50 | 172 printings | [41449050457](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41449050457) |
| MTGJSON Magic Foundations (FDN), offset 550, limit 100 | 100 | 100 print/finish variants | [41449175051](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41449175051) |
| Rebrickable LEGO 2026 eligible sets, offset 550, limit 100 | 100 | 100 set models | [41449175051](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41449175051) |
| YGOPRODeck Yu-Gi-Oh TCG, offset 275, limit 50 | 50 | 139 printings | [41449175051](https://github.com/pulltheorytcg/drop-rate-backend/actions/runs/41449175051) |
| **Totals (candidate occurrences, before cross-run deduplication)** | **1,500** | **2,384** | |

## Validation and safety

- All six distinct source-preview workflows concluded **success**. The CI validator asserted
  zero Supabase writes, R2 uploads, mirrored images, verified market values,
  and Shopify products in all 18 preview reports.
- The workflows have only `contents: read` GitHub permissions and do not
  receive production, R2 or Shopify credentials.
- The first batch's 7-day JSON report artifact is ID `13109546054`;
  the second batch's is `13110160160`. The third through sixth batch artifacts are `13143690383`, `13143605424`, `13143671561` and `13143302661`; all have 7-day retention through 9 November 2026.
- Each run validates uniqueness within its own window. The **2,384 total is not
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
session); the app's Railway `tcg_api` role cannot perform DDL. A fresh read-only query on 2 November measured the database at **419,007,635 bytes**, already above the importer's **400,000,000-byte** safety threshold, while the original **69,697 reference cards**, **1,472 sets**, and **14 system codes** were unchanged; figure-schema tables are absent. Production
database headroom is limited, so the bulk catalogue should remain R2-first,
with only bounded, indexed identities/materialized records in Supabase after
reviewed capacity tests.

No app deployment, production schema write, R2 feed activation, provider-image
copy or Shopify listing has been authorized by these preview results.

## Private R2 metadata archive preparation (not activated)

The draft PR now has an explicit, opt-in Magic metadata-only archive path in
`backend/scripts/pilot_expanded_catalogues.py`. It is limited to normalized
MTGJSON set/printing/finish identities, uses a closed field allowlist, removes
provider artwork and prices, and writes only to an existing private R2
content-addressed source-input location. It verifies a full remote readback
before claiming a receipt. Calling `--archive-private-r2` requires both
`--source magic`, configured object storage, and
`TCG_MAGIC_METADATA_R2_ARCHIVE_ENABLED=true`. The default dry run does not
attempt a storage connection or write. A separate automated contract test
verified the flag gate, source guard, exclusion of images/prices and readback
failure handling in disposable CI.

**No private R2 archive was uploaded in these six runs.** MTGJSON source
attribution/licensing must accompany any later published dataset; its MIT data
license does not convey artwork rights. There is no approved automated
Rebrickable commercial reuse, Funko/Topps/Panini bulk feed, Lorcana
redistribution, or Riot Riftbound asset feed yet.

Next bounded offsets after these receipts: MTGJSON FDN `650`, eligible LEGO
2026 `650`, and YGOPRODeck TCG `325`. Do not treat bounded validations as
seller inventory or activate SQL/R2/Shopify publication until the separate
source-rights, migration, database capacity and live-app gates are satisfied.
