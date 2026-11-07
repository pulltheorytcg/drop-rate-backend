# UK sold evidence normalization

Drop Rate's existing pricing engine remains responsible for robust valuation.
This change corrects the connected Trawl feed before card, slab, comic, manga
and sealed-product matching. It does not add a provider, change seller prices,
publish inventory, or replace Cardmarket's separate guide path.

## Changes

- Require UK item-location evidence; an eBay UK marketplace result alone is insufficient.
- Convert provider search wall times to UTC at the HTTP boundary. Do not reinterpret stored UTC history. Reject ambiguous daylight-saving times.
- Exclude unresolved offers and unknown sale formats. Accept an offered price only when listing identity, UTC sale instant, currency, accepted-offer flag and lower price against the matching asking price agree.
- Keep unknown, free and paid postage distinct; value the item separately.
- Deduplicate identical listing evidence and reject conflicting duplicates independent of response order.
- Preserve minimal provenance in observations and inventory/catalogue snapshots, with aggregate exclusion reasons in ingestion receipts. Do not retain seller profiles or descriptions.
- Append versioned evidence when an old listing is rechecked. A physical pricing basis with normalized evidence uses that evidence without padding it with unverified legacy rows. Unrechecked legacy bases retain their existing behavior.

The provider contract is documented at [sold search](https://trawl.dev/docs/ebay/sold)
and [item details](https://trawl.dev/docs/ebay/item). This code makes no additional
details requests and does not increase page limits or bypass existing retry controls.

## Validation and limitations

Tests cover location, timestamps/DST, amounts, offer identity and price, unknown
postage, duplicates, API quota handling, private-field exclusion, immutable
insertion/idempotency, exact matches across existing collectible paths, and
catalogue replay with legacy evidence. Existing pricing and ownership tests remain required.

Local synchronous validation passed; the Windows environment cannot create the
asyncio event-loop socket pair, so Linux CI must validate async and PostgreSQL paths
before merge. No production schema migration is required.

The live feed's last successful receipt on 1 November recorded zero of 250
credits remaining. Later receipts through 4 November contain HTTP 429 failures.
Fresh production provider validation is blocked until quota is restored.

This is an evidence-integrity improvement, not a measured new accuracy score.
The prior replay in PR #910 remains the baseline. Legacy rows are not relabelled
as verified, and their missing original location/offer fields cannot be reconstructed.
Figures/Funko still require exact sales evidence and a supported matching path;
this release does not invent figure valuations or claim complete catalogue coverage.
